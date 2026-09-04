import hashlib
import json
import time
from typing import Optional
from pydantic import BaseModel, Field
from app.config import settings
from app.gateway.ap2_schema import ap2_verifier, AP2PaymentMandate
from app.db.crypto_vault import crypto_vault

class PaymentToolPayload(BaseModel):
    session_id: str
    intent_id: str
    merchant_id: str
    amount_inr: float = Field(gt=0, description="Amount must be strictly positive")
    currency: str
    nonce: str
    user_max_budget: float
    product_sku: str
    quantity: int = Field(gt=0)
    cart_hash: Optional[str] = None
    ap2_mandate: Optional[AP2PaymentMandate] = None

    def resolved_cart_hash(self) -> str:
        if self.cart_hash:
            return self.cart_hash
        cart = {"product_sku": self.product_sku, "quantity": self.quantity}
        return hashlib.sha256(json.dumps(cart, sort_keys=True).encode()).hexdigest()

    def idempotency_fingerprint(self) -> str:
        value = f"{self.session_id}|{self.merchant_id}|{self.amount_inr}|{self.resolved_cart_hash()}"
        return hashlib.sha256(value.encode()).hexdigest()


class ActionBoundedError(Exception):
    """Raised when an agent action needs an interactive payment step-up."""

    pass

class DeterministicValidationResult(BaseModel):
    is_valid: bool
    violation_code: Optional[str] = None
    reason: Optional[str] = None
    latency_ms: float

class DeterministicRulesEngine:
    async def validate(self, payload: PaymentToolPayload) -> DeterministicValidationResult:
        start_time = time.perf_counter()

        # Rule 1: Currency Lock
        if payload.currency.upper() != settings.ALLOWED_CURRENCY:
            elapsed = (time.perf_counter() - start_time) * 1000
            return DeterministicValidationResult(
                is_valid=False,
                violation_code="CURRENCY_MISMATCH",
                reason=f"Currency '{payload.currency}' is rejected. Only '{settings.ALLOWED_CURRENCY}' is permitted.",
                latency_ms=elapsed
            )

        # Rule 2: AP2 Cryptographic Mandate Signature Verification
        if payload.ap2_mandate:
            if not ap2_verifier.verify_mandate(payload.ap2_mandate):
                elapsed = (time.perf_counter() - start_time) * 1000
                return DeterministicValidationResult(
                    is_valid=False,
                    violation_code="INVALID_AP2_MANDATE",
                    reason="AP2 cryptographic mandate token signature is invalid or expired.",
                    latency_ms=elapsed
                )

        # Rule 3: User Authorized Budget Invariant (Fixed Encoding)
        if payload.amount_inr > payload.user_max_budget:
            elapsed = (time.perf_counter() - start_time) * 1000
            return DeterministicValidationResult(
                is_valid=False,
                violation_code="BUDGET_OVERRUN",
                reason=f"Attempted amount ₹{payload.amount_inr:,.2f} exceeds user-defined budget cap of ₹{payload.user_max_budget:,.2f}.",
                latency_ms=elapsed
            )

        # Rule 4: Gateway Hard Spend Ceiling
        if payload.amount_inr > settings.MAX_SESSION_SPEND_INR:
            elapsed = (time.perf_counter() - start_time) * 1000
            return DeterministicValidationResult(
                is_valid=False,
                violation_code="SYSTEM_SPEND_CAP_EXCEEDED",
                reason=f"Amount ₹{payload.amount_inr:,.2f} breaches gateway ceiling of ₹{settings.MAX_SESSION_SPEND_INR:,.2f}.",
                latency_ms=elapsed
            )

        # Rule 5: Merchant Allowlist Enforcement
        if payload.merchant_id not in settings.ALLOWED_MERCHANTS:
            elapsed = (time.perf_counter() - start_time) * 1000
            return DeterministicValidationResult(
                is_valid=False,
                violation_code="UNAUTHORIZED_MERCHANT",
                reason=f"Merchant '{payload.merchant_id}' is not in the verified gateway registry.",
                latency_ms=elapsed
            )

        # Rule 6: Persistent Cryptographic Nonce & Replay Prevention
        nonce_signature = hashlib.sha256(
            f"{payload.session_id}:{payload.nonce}:{payload.amount_inr}".encode()
        ).hexdigest()

        if await crypto_vault.is_nonce_consumed(nonce_signature):
            elapsed = (time.perf_counter() - start_time) * 1000
            return DeterministicValidationResult(
                is_valid=False,
                violation_code="REPLAY_ATTACK_DETECTED",
                reason="Cryptographic nonce signature has already been consumed.",
                latency_ms=elapsed
            )

        await crypto_vault.consume_nonce(nonce_signature, payload.session_id)
        if payload.amount_inr > settings.MAX_AUTONOMOUS_TRANSACTION_INR:
            raise ActionBoundedError(
                f"Autonomous transaction limit is ₹{settings.MAX_AUTONOMOUS_TRANSACTION_INR:,.2f}; "
                "an interactive payment step-up is required."
            )
        elapsed = (time.perf_counter() - start_time) * 1000

        return DeterministicValidationResult(
            is_valid=True,
            violation_code=None,
            reason="All deterministic invariants verified successfully.",
            latency_ms=elapsed
        )

deterministic_engine = DeterministicRulesEngine()