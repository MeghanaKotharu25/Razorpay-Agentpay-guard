import razorpay
from typing import Dict, Any
from app.config import settings

class RazorpayTestClient:
    def __init__(self):
        self.key_id = (settings.RAZORPAY_KEY_ID or "").strip()
        self.key_secret = (settings.RAZORPAY_KEY_SECRET or "").strip()
        
        # Check if the keys are actual live test keys or unconfigured templates
        self.is_configured = bool(
            self.key_id 
            and not self.key_id.startswith("rzp_test_placeholder") 
            and "yourKeyId" not in self.key_id
            and self.key_secret
            and "yourKeySecret" not in self.key_secret
        )
        
        if self.is_configured:
            self.client = razorpay.Client(auth=(self.key_id, self.key_secret))
        else:
            self.client = None

    def create_order(
        self, 
        amount_inr: float, 
        currency: str, 
        receipt_id: str, 
        notes: Dict[str, str]
    ) -> Dict[str, Any]:
        """Creates an order, with graceful fallback to simulated sandbox responses."""
        amount_paise = int(amount_inr * 100)
        payload = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt_id,
            "notes": notes,
            "payment_capture": 1
        }

        if self.is_configured and self.client:
            try:
                return self.client.order.create(data=payload)
            except Exception:
                # Fall through to simulated sandbox payload on auth/network failure
                pass

        # Built-in Simulated Test Sandbox Response
        return {
            "id": f"order_test_mock_{receipt_id}",
            "entity": "order",
            "amount": amount_paise,
            "amount_paid": 0,
            "amount_due": amount_paise,
            "currency": currency,
            "receipt": receipt_id,
            "status": "created",
            "notes": notes
        }

razorpay_client = RazorpayTestClient()