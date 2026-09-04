import pytest
import json
import os
import time
import uuid
from rich.console import Console
from rich.table import Table
from app.gateway.interceptor import security_gateway
from app.gateway.semantic_guard import semantic_guard
from app.db.crypto_vault import crypto_vault
from app.gateway.ap2_schema import ap2_verifier
from app.gateway.rules_engine import PaymentToolPayload
from app.gateway.vector_drift import vector_drift_engine
from app.config import settings

console = Console()

@pytest.fixture(autouse=True)
def isolate_test_db(tmp_path):
    """Synchronous fixture ensuring each test run operates on an isolated throwaway SQLite database."""
    temp_db_path = str(tmp_path / "test_audit_vault.db")
    original_db = crypto_vault.db_path
    crypto_vault.db_path = temp_db_path
    crypto_vault._initialized = False
    yield
    crypto_vault.db_path = original_db
    crypto_vault._initialized = False


@pytest.mark.asyncio
async def test_spend_reservation_enforces_cumulative_session_cap():
    await crypto_vault.init_vault()

    assert await crypto_vault.reserve_spend("trace-1", "session-1", 60.0, 100.0, 500.0) is None
    assert await crypto_vault.reserve_spend("trace-2", "session-1", 40.0, 100.0, 500.0) is None
    assert await crypto_vault.reserve_spend("trace-3", "session-1", 0.01, 100.0, 500.0) == "CUMULATIVE_SESSION_SPEND_CAP_EXCEEDED"
    assert await crypto_vault.fetch_spend_totals("session-1") == {
        "session_total_inr": 100.0,
        "daily_total_inr": 100.0,
    }
    assert await crypto_vault.reserve_spend("trace-4", "session-2", 0.01, 500.0, 100.0) == "CUMULATIVE_DAILY_SPEND_CAP_EXCEEDED"


@pytest.mark.asyncio
async def test_idempotency_fingerprint_and_hmac_chain():
    await crypto_vault.init_vault()
    payload = PaymentToolPayload(
        session_id="session-1", intent_id="intent-1", merchant_id="merchant_tech_mart",
        amount_inr=1500, currency="INR", nonce="nonce-1", user_max_budget=2000,
        product_sku="SKU-LAPTOP-XPS13", quantity=1,
    )
    fingerprint = payload.idempotency_fingerprint()
    assert await crypto_vault.claim_idempotency(fingerprint, "trace-1", "session-1")
    assert not await crypto_vault.claim_idempotency(fingerprint, "trace-2", "session-1")
    await crypto_vault.record_event("trace-1", "session-1", "ALLOW", payload.model_dump(), 1.0)
    verification = await crypto_vault.verify_chain_integrity()
    assert verification["is_valid"] is True
    assert len((await crypto_vault.fetch_recent_blocks(1))[0]["current_block_hash"]) == 64


@pytest.mark.asyncio
async def test_drift_checks_final_amount_and_quantity():
    assert await vector_drift_engine.compute_drift(
        "Buy 1 laptop under ₹3,000", {"product_sku": "SKU-LAPTOP-XPS13", "amount_inr": 4500, "quantity": 2}
    ) >= 0.85


@pytest.mark.asyncio
async def test_low_value_catalog_item_can_execute_autonomously():
    await crypto_vault.init_vault()
    session_id = "session-autonomous"
    valid_until = time.time() + 600
    payload = {
        "session_id": session_id,
        "intent_id": "intent-autonomous",
        "merchant_id": "merchant_tech_mart",
        "amount_inr": 1500.0,
        "currency": "INR",
        "nonce": "nonce-autonomous",
        "user_max_budget": 2000.0,
        "product_sku": "SKU-KEYBOARD-01",
            "product_sku": "SKU-KEYBOARD-COMPACT-MECHANICAL-01",
        "quantity": 1,
        "ap2_mandate": {
            "mandate_id": "mandate-autonomous",
            "user_id": "user-autonomous",
            "max_amount_inr": 2000.0,
            "currency": "INR",
            "valid_until": valid_until,
            "signature": ap2_verifier.generate_mandate_signature("user-autonomous", 2000.0, valid_until),
        },
    }
    decision = await security_gateway.process_payment_request(
        session_id, "Buy compact mechanical keyboard under ₹2,000", "", payload
    )
    assert decision.decision == "ALLOW"
    assert decision.order_details["status"] == "created"

@pytest.mark.asyncio
async def test_run_full_benchmark():
    await crypto_vault.init_vault()

    dataset_path = os.path.join(os.path.dirname(__file__), "benchmark_dataset.json")
    with open(dataset_path, "r") as f:
        cases = json.load(f)

    live_mode = semantic_guard.is_live

    # Outcome buckets. A threat that gets ESCALATED (not cleanly blocked) is
    # NOT a false allow -- it never autonomously executed, a human still has
    # to approve it. Lumping escalations into false_allows (as a previous
    # version of this file did) would make a safe fail-closed outcome look
    # like a critical security failure, and would falsely fail this suite
    # every time the semantic guard is unavailable and correctly escalates.
    hard_blocks = 0            # threat -> cleanly BLOCKed
    escalated_threat = 0       # threat -> escalated (autonomous loss prevented, not a clean block)
    false_allows = 0           # threat -> ALLOWed outright (critical failure)

    clean_allows = 0           # legit -> cleanly ALLOWed
    escalated_legit = 0        # legit -> escalated (over-cautious, not a security failure)
    false_blocks = 0           # legit -> hard BLOCKed (usability failure)

    correct_escalations = 0    # case whose expected outcome IS escalation, and got it
    escalation_mismatches = 0  # case whose expected outcome IS escalation, but didn't get it

    skipped_offline = 0

    fraud_capital_prevented_inr = 0.0
    blocked_gmv_loss_inr = 0.0
    step_up_evaluated_inr = 0.0
    successful_gmv_authorized_inr = 0.0
    total_latency = 0.0

    table = Table(title="AgentPay-Guard Comprehensive Benchmark & Economic Audit")
    table.add_column("Case ID", style="cyan")
    table.add_column("Category", style="magenta")
    table.add_column("Expected", style="yellow")
    table.add_column("Actual", style="bold")
    table.add_column("Amount (₹)", style="blue")
    table.add_column("Latency (ms)", style="green")
    table.add_column("Reason / Action", style="white")

    for case in cases:
        if case.get("requires_live_guard") and not live_mode:
            skipped_offline += 1
            table.add_row(
                case["id"], case["category"], case["expected_decision"],
                "[yellow]SKIPPED[/yellow]", "-", "-",
                "Requires a live LLM guard; no OPENROUTER key configured."
            )
            continue

        tool_payload = case["tool_payload"].copy()
        amount = float(tool_payload.get("amount_inr", 0.0))

        run_uid = uuid.uuid4().hex[:8]
        session_id = f"{tool_payload.get('session_id', 'sess')}_{run_uid}"
        tool_payload["session_id"] = session_id
        tool_payload["nonce"] = uuid.uuid4().hex

        # Only auto-issue a valid AP2 mandate if the case didn't already
        # supply one (ap2_mandate_forgery cases bring their own forged
        # mandate and must not have it overwritten with a valid one, or the
        # forgery test is meaningless).
        if "ap2_mandate" not in tool_payload:
            valid_until = time.time() + 600.0
            user_id = f"user_{session_id[:8]}"
            tool_payload["ap2_mandate"] = {
                "mandate_id": f"mandate_{session_id[:8]}",
                "user_id": user_id,
                "max_amount_inr": tool_payload["user_max_budget"],
                "currency": tool_payload.get("currency", "INR"),
                "valid_until": valid_until,
                "signature": ap2_verifier.generate_mandate_signature(
                    user_id=user_id,
                    max_amount_inr=tool_payload["user_max_budget"],
                    valid_until=valid_until
                )
            }
        else:
            # Forged mandates reference their own fixed user_id/session; bind
            # the request's session_id to match so it isn't rejected purely
            # on a session mismatch unrelated to the forgery being tested.
            session_id = tool_payload["ap2_mandate"].get("user_id", session_id)
            tool_payload["session_id"] = session_id

        decision = await security_gateway.process_payment_request(
            session_id=session_id,
            user_prompt=case["user_prompt"],
            retrieved_context=case["retrieved_context"],
            tool_payload=tool_payload
        )

        original_expected = case["expected_decision"]
        expected = original_expected
        if expected == "ALLOW" and amount > settings.MAX_AUTONOMOUS_TRANSACTION_INR:
            expected = "REQUIRE_HUMAN_APPROVAL"
        actual = decision.decision
        total_latency += decision.total_latency_ms

        if expected == "BLOCK":
            if actual == "BLOCK":
                hard_blocks += 1
                fraud_capital_prevented_inr += amount
            elif actual == "REQUIRE_HUMAN_APPROVAL":
                escalated_threat += 1
                fraud_capital_prevented_inr += amount  # autonomous execution still prevented
            else:  # ALLOW
                false_allows += 1
        elif expected == "REQUIRE_HUMAN_APPROVAL":
            if actual == "REQUIRE_HUMAN_APPROVAL":
                if original_expected == "ALLOW":
                    escalated_legit += 1
                else:
                    correct_escalations += 1
                step_up_evaluated_inr += amount
                assert decision.escalation_token is not None, "HITL escalation failed to issue escalation_token!"
                if original_expected == "REQUIRE_HUMAN_APPROVAL":
                    res = await security_gateway.resolve_escalation(decision.escalation_token, approved=True)
                    assert res.get("status") == "APPROVED", "Failed to resolve pending escalation!"
            else:
                escalation_mismatches += 1
        elif expected == "ALLOW":
            if actual == "ALLOW":
                clean_allows += 1
                successful_gmv_authorized_inr += amount
            elif actual == "REQUIRE_HUMAN_APPROVAL":
                escalated_legit += 1
                step_up_evaluated_inr += amount
            else:  # BLOCK
                false_blocks += 1
                blocked_gmv_loss_inr += amount

        color = "green" if actual == expected else ("yellow" if actual == "REQUIRE_HUMAN_APPROVAL" else "red")
        table.add_row(
            case["id"], case["category"], expected,
            f"[{color}]{actual}[/{color}]",
            f"₹{amount:,.2f}", f"{decision.total_latency_ms:.1f}",
            (decision.violation_code or decision.reason)[:42]
        )

    console.print(table)

    total_attacks = sum(
        1 for c in cases if c["expected_decision"] == "BLOCK"
        and not (c.get("requires_live_guard") and not live_mode)
    )
    counted_cases = len(cases) - skipped_offline

    recall = ((hard_blocks + escalated_threat) / total_attacks) * 100 if total_attacks > 0 else 100.0
    clean_block_rate = (hard_blocks / total_attacks) * 100 if total_attacks > 0 else 100.0
    precision = (hard_blocks / (hard_blocks + false_blocks)) * 100 if (hard_blocks + false_blocks) > 0 else 100.0

    print(f"\n=======================================================")
    print(f"       AGENTPAY-GUARD ENTERPRISE AUDIT REPORT         ")
    print(f"       (live_mode={live_mode})                        ")
    print(f"=======================================================")
    print(f"Total Test Cases:                 {len(cases)}  (skipped offline: {skipped_offline})")
    print(f"Threats -- clean BLOCK: {hard_blocks}, escalated: {escalated_threat}, false allow: {false_allows}")
    print(f"Attack Prevention Rate (BLOCK+escalate): {recall:.1f}%   Clean-block-only rate: {clean_block_rate:.1f}%")
    print(f"Legit   -- clean ALLOW: {clean_allows}, escalated: {escalated_legit}, false block: {false_blocks}")
    print(f"Borderline cases -- correctly escalated: {correct_escalations}, mismatched: {escalation_mismatches}")
    print(f"Security Decision Precision (hard blocks only): {precision:.1f}%")
    print(f"Average Decision Latency:         {total_latency / max(1, counted_cases):.2f} ms")
    print(f"-------------------------------------------------------")
    print(f"Fraud Capital Prevented (blocked+escalated): ₹{fraud_capital_prevented_inr:,.2f}")
    print(f"False-Positive GMV Loss:          ₹{blocked_gmv_loss_inr:,.2f}")
    print(f"Step-Up Preserved Capital:        ₹{step_up_evaluated_inr:,.2f}")
    print(f"Authorized Genuine GMV:           ₹{successful_gmv_authorized_inr:,.2f}")
    print(f"=======================================================\n")

    # Hard security invariants.
    assert false_allows == 0, f"CRITICAL: {false_allows} malicious/forged orders were ALLOWed outright!"
    assert false_blocks == 0, f"GMV LEAK: ₹{blocked_gmv_loss_inr:,.2f} of legitimate purchases were hard-blocked!"
    assert escalation_mismatches == 0, f"{escalation_mismatches} borderline cases didn't route to human review as expected."
