import hashlib
import hmac
import time
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from app.config import settings

class AP2PaymentMandate(BaseModel):
    mandate_id: str
    user_id: str
    max_amount_inr: float
    currency: str = "INR"
    valid_until: float
    signature: str  # Simplified HMAC-SHA256 AP2 mandate simulation for the demo

class X402PaymentChallenge(BaseModel):
    status: int = 402
    resource_id: str
    amount_inr: float
    currency: str = "INR"
    beneficiary_merchant_id: str
    nonce: str
    mandate_required: bool = True

class AP2TokenVerifier:
    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = secret_key or settings.AP2_SIGNING_SECRET

    def generate_mandate_signature(self, user_id: str, max_amount_inr: float, valid_until: float) -> str:
        payload = f"{user_id}:{max_amount_inr}:{valid_until}".encode()
        return hmac.new(self.secret_key.encode(), payload, hashlib.sha256).hexdigest()

    def verify_mandate(self, mandate: AP2PaymentMandate) -> bool:
        if time.time() > mandate.valid_until:
            return False
        expected_sig = self.generate_mandate_signature(
            mandate.user_id, mandate.max_amount_inr, mandate.valid_until
        )
        return hmac.compare_digest(expected_sig, mandate.signature)

ap2_verifier = AP2TokenVerifier()