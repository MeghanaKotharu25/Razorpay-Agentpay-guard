import uuid
import time
from typing import Dict, Any, Optional
from pydantic import BaseModel
from app.gateway.rules_engine import deterministic_engine, PaymentToolPayload, ActionBoundedError
from app.gateway.semantic_guard import semantic_guard, GuardServiceUnavailableError
from app.gateway.vector_drift import vector_drift_engine
from app.integrations.razorpay_client import razorpay_client
from app.db.crypto_vault import crypto_vault
from app.config import settings

class GatewayDecision(BaseModel):
    trace_id: str
    session_id: str
    decision: str  # ALLOW, BLOCK, or REQUIRE_HUMAN_APPROVAL
    violation_code: Optional[str] = None
    reason: str
    total_latency_ms: float
    semantic_drift_score: Optional[float] = None
    block_hash: Optional[str] = None
    order_details: Optional[Dict[str, Any]] = None
    escalation_token: Optional[str] = None

class SecurityGatewayInterceptor:
    async def process_payment_request(
        self,
        session_id: str,
        user_prompt: str,
        retrieved_context: str,
        tool_payload: Dict[str, Any]
    ) -> GatewayDecision:
        start_time = time.perf_counter()
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"

        # Step 1: Strict Schema Validation
        try:
            parsed_payload = PaymentToolPayload(**tool_payload)
        except Exception as e:
            elapsed = (time.perf_counter() - start_time) * 1000
            block_hash = await crypto_vault.record_event(
                trace_id=trace_id,
                session_id=session_id,
                decision="BLOCK",
                payload=tool_payload,
                latency_ms=elapsed,
                user_prompt=user_prompt,
                violation_code="MALFORMED_TOOL_SCHEMA",
                reason=f"Schema validation error: {str(e)}"
            )
            return GatewayDecision(
                trace_id=trace_id,
                session_id=session_id,
                decision="BLOCK",
                violation_code="MALFORMED_TOOL_SCHEMA",
                reason=f"Schema parsing error: {str(e)}",
                total_latency_ms=elapsed,
                block_hash=block_hash
            )

        # Step 2: Tier-0 Deterministic Invariant Check (<0.1ms)
        try:
            fingerprint = parsed_payload.idempotency_fingerprint()
            if not await crypto_vault.claim_idempotency(fingerprint, trace_id, session_id):
                raise ActionBoundedError("Duplicate payment fingerprint detected; retry suppressed safely.")
            rule_result = await deterministic_engine.validate(parsed_payload)
        except ActionBoundedError as e:
            elapsed = (time.perf_counter() - start_time) * 1000
            is_duplicate = "Duplicate" in str(e)
            violation = "IDEMPOTENCY_REPLAY" if is_duplicate else "ACTION_BOUNDED"
            payment_link = None if is_duplicate else razorpay_client.create_payment_link(
                amount_inr=parsed_payload.amount_inr,
                currency=parsed_payload.currency,
                receipt_id=parsed_payload.intent_id,
                notes={"session_id": session_id, "bounded": "true"},
            )
            escalation_token = None
            if not is_duplicate:
                escalation_token = f"esc_{uuid.uuid4().hex[:12]}"
                await crypto_vault.save_pending_escalation(
                    escalation_token=escalation_token,
                    trace_id=trace_id,
                    session_id=session_id,
                    user_prompt=user_prompt,
                    payload=parsed_payload.model_dump(),
                )
            block_hash = await crypto_vault.record_event(
                trace_id=trace_id, session_id=session_id,
                decision="REQUIRE_HUMAN_APPROVAL" if not is_duplicate else "BLOCK",
                payload=tool_payload, latency_ms=elapsed, user_prompt=user_prompt,
                violation_code=violation, reason=str(e),
            )
            return GatewayDecision(
                trace_id=trace_id, session_id=session_id,
                decision="REQUIRE_HUMAN_APPROVAL" if not is_duplicate else "BLOCK",
                violation_code=violation, reason=str(e), total_latency_ms=elapsed,
                order_details=payment_link, escalation_token=escalation_token,
                block_hash=block_hash,
            )
        if not rule_result.is_valid:
            elapsed = (time.perf_counter() - start_time) * 1000
            block_hash = await crypto_vault.record_event(
                trace_id=trace_id,
                session_id=session_id,
                decision="BLOCK",
                payload=tool_payload,
                latency_ms=elapsed,
                user_prompt=user_prompt,
                violation_code=rule_result.violation_code,
                reason=rule_result.reason
            )
            return GatewayDecision(
                trace_id=trace_id,
                session_id=session_id,
                decision="BLOCK",
                violation_code=rule_result.violation_code,
                reason=rule_result.reason or "Deterministic policy violation",
                total_latency_ms=elapsed,
                block_hash=block_hash
            )

        # Step 3: Tier-1 Latent Vector Drift & Semantic Guard
        # semantic_guard.inspect() raises GuardServiceUnavailableError instead
        # of returning a fake-safe result when the LLM call fails. That
        # exception is caught here and routed to human review — an outage
        # in the guard is a reason to slow down, never a reason to let a
        # transaction through unverified.
        vector_drift = await vector_drift_engine.compute_drift(user_prompt, parsed_payload.model_dump())

        try:
            semantic_result = await semantic_guard.inspect(
                user_prompt=user_prompt,
                retrieved_context=retrieved_context,
                proposed_tool_payload=tool_payload
            )
        except GuardServiceUnavailableError as e:
            elapsed = (time.perf_counter() - start_time) * 1000
            escalation_token = f"esc_{uuid.uuid4().hex[:12]}"
            await crypto_vault.save_pending_escalation(
                escalation_token=escalation_token,
                trace_id=trace_id,
                session_id=session_id,
                user_prompt=user_prompt,
                payload=parsed_payload.model_dump()
            )
            block_hash = await crypto_vault.record_event(
                trace_id=trace_id,
                session_id=session_id,
                decision="REQUIRE_HUMAN_APPROVAL",
                payload=tool_payload,
                latency_ms=elapsed,
                user_prompt=user_prompt,
                violation_code="GUARD_SERVICE_UNAVAILABLE",
                reason=str(e)
            )
            return GatewayDecision(
                trace_id=trace_id,
                session_id=session_id,
                decision="REQUIRE_HUMAN_APPROVAL",
                violation_code="GUARD_SERVICE_UNAVAILABLE",
                reason=(
                    "Automated semantic inspection could not complete "
                    f"({str(e)[:100]}). Failing closed: human approval is "
                    "required before this transaction can proceed."
                ),
                total_latency_ms=elapsed,
                semantic_drift_score=vector_drift,
                escalation_token=escalation_token,
                block_hash=block_hash
            )

        # Highest risk score governs
        effective_drift = max(vector_drift, semantic_result.drift_score)

        # Hard BLOCK: Injection Detected OR Unsafe OR Severe Intent Drift (>= 0.70)
        if semantic_result.injection_detected or not semantic_result.is_safe or effective_drift >= 0.70:
            elapsed = (time.perf_counter() - start_time) * 1000
            violation = "PROMPT_INJECTION_DETECTED" if semantic_result.injection_detected else "INTENT_DRIFT_EXCEEDED"
            reason_str = semantic_result.violation_reason or f"Severe intent drift detected (Drift: {effective_drift:.2f})."
            block_hash = await crypto_vault.record_event(
                trace_id=trace_id,
                session_id=session_id,
                decision="BLOCK",
                payload=tool_payload,
                latency_ms=elapsed,
                user_prompt=user_prompt,
                violation_code=violation,
                reason=reason_str
            )
            return GatewayDecision(
                trace_id=trace_id,
                session_id=session_id,
                decision="BLOCK",
                violation_code=violation,
                reason=reason_str,
                total_latency_ms=elapsed,
                semantic_drift_score=effective_drift,
                block_hash=block_hash
            )

        # Step 4: Step-Up HITL Escalation (0.35 <= drift < 0.70)
        if 0.35 <= effective_drift < 0.70:
            elapsed = (time.perf_counter() - start_time) * 1000
            escalation_token = f"esc_{uuid.uuid4().hex[:12]}"
            await crypto_vault.save_pending_escalation(
                escalation_token=escalation_token,
                trace_id=trace_id,
                session_id=session_id,
                user_prompt=user_prompt,
                payload=parsed_payload.model_dump()
            )
            block_hash = await crypto_vault.record_event(
                trace_id=trace_id,
                session_id=session_id,
                decision="REQUIRE_HUMAN_APPROVAL",
                payload=tool_payload,
                latency_ms=elapsed,
                user_prompt=user_prompt,
                violation_code="BORDERLINE_INTENT_DRIFT",
                reason=semantic_result.violation_reason or f"Purchase requires 1-click step-up confirmation (Drift: {effective_drift:.2f})."
            )
            return GatewayDecision(
                trace_id=trace_id,
                session_id=session_id,
                decision="REQUIRE_HUMAN_APPROVAL",
                violation_code="BORDERLINE_INTENT_DRIFT",
                reason=semantic_result.violation_reason or f"Purchase requires 1-click confirmation due to product variance (Drift: {effective_drift:.2f}).",
                total_latency_ms=elapsed,
                semantic_drift_score=effective_drift,
                escalation_token=escalation_token,
                block_hash=block_hash
            )

        # Step 5: Clean ALLOW (< 0.35 drift) & Razorpay Execution
        spend_violation = await crypto_vault.reserve_spend(
            trace_id=trace_id,
            session_id=session_id,
            amount_inr=parsed_payload.amount_inr,
            session_limit_inr=settings.MAX_SESSION_SPEND_INR,
            daily_limit_inr=settings.MAX_DAILY_SPEND_INR,
        )
        if spend_violation:
            elapsed = (time.perf_counter() - start_time) * 1000
            reason = "Cumulative authorized spend limit exceeded; transaction blocked."
            block_hash = await crypto_vault.record_event(
                trace_id=trace_id, session_id=session_id, decision="BLOCK",
                payload=tool_payload, latency_ms=elapsed, user_prompt=user_prompt,
                violation_code=spend_violation, reason=reason,
            )
            return GatewayDecision(
                trace_id=trace_id, session_id=session_id, decision="BLOCK",
                violation_code=spend_violation, reason=reason,
                total_latency_ms=elapsed, semantic_drift_score=effective_drift,
                block_hash=block_hash,
            )
        order_res = razorpay_client.create_order(
            amount_inr=parsed_payload.amount_inr,
            currency=parsed_payload.currency,
            receipt_id=parsed_payload.intent_id,
            notes={
                "session_id": session_id,
                "sku": parsed_payload.product_sku,
                "merchant_id": parsed_payload.merchant_id
            }
        )

        elapsed = (time.perf_counter() - start_time) * 1000
        block_hash = await crypto_vault.record_event(
            trace_id=trace_id,
            session_id=session_id,
            decision="ALLOW",
            payload=tool_payload,
            latency_ms=elapsed,
            user_prompt=user_prompt,
            reason="Verified and dispatched to Razorpay Sandbox."
        )

        return GatewayDecision(
            trace_id=trace_id,
            session_id=session_id,
            decision="ALLOW",
            reason="Verified and dispatched to Razorpay Sandbox.",
            total_latency_ms=elapsed,
            semantic_drift_score=effective_drift,
            order_details=order_res,
            block_hash=block_hash
        )

    async def resolve_escalation(self, escalation_token: str, approved: bool) -> Dict[str, Any]:
        record = await crypto_vault.pop_pending_escalation(escalation_token)
        if not record:
            return {"error": "Invalid or expired escalation token"}

        payload = record["payload"]
        trace_id = record["trace_id"]
        session_id = record["session_id"]
        user_prompt = record["user_prompt"]

        if not approved:
            block_hash = await crypto_vault.record_event(
                trace_id=trace_id,
                session_id=session_id,
                decision="BLOCK",
                payload=payload,
                latency_ms=0.0,
                user_prompt=user_prompt,
                violation_code="USER_REJECTED_ESCALATION",
                reason="User declined step-up authentication consent."
            )
            return {"status": "REJECTED", "trace_id": trace_id, "block_hash": block_hash}

        spend_violation = await crypto_vault.reserve_spend(
            trace_id=trace_id,
            session_id=session_id,
            amount_inr=payload["amount_inr"],
            session_limit_inr=settings.MAX_SESSION_SPEND_INR,
            daily_limit_inr=settings.MAX_DAILY_SPEND_INR,
        )
        if spend_violation:
            block_hash = await crypto_vault.record_event(
                trace_id=trace_id, session_id=session_id, decision="BLOCK",
                payload=payload, latency_ms=0.0, user_prompt=user_prompt,
                violation_code=spend_violation,
                reason="Cumulative authorized spend limit exceeded after human approval.",
            )
            return {"status": "BLOCKED", "trace_id": trace_id, "block_hash": block_hash}
        order_res = razorpay_client.create_order(
            amount_inr=payload["amount_inr"],
            currency=payload["currency"],
            receipt_id=payload["intent_id"],
            notes={
                "session_id": session_id,
                "sku": payload["product_sku"],
                "merchant_id": payload["merchant_id"],
                "escalation_approved": "true"
            }
        )

        block_hash = await crypto_vault.record_event(
            trace_id=trace_id,
            session_id=session_id,
            decision="ALLOW",
            payload=payload,
            latency_ms=0.0,
            user_prompt=user_prompt,
            reason="Human verified and approved transaction."
        )

        return {"status": "APPROVED", "trace_id": trace_id, "order": order_res, "block_hash": block_hash}

security_gateway = SecurityGatewayInterceptor()