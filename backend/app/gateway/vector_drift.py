import re
from typing import Set
from typing import Any, Dict

class LexicalCategoryDriftEngine:

    def _tokenize(self, text: str) -> Set[str]:
        # Split camelCase, snake_case, and alphanumeric boundaries (e.g. xps13 -> xps, 13)
        cleaned = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', text)
        tokens = set(re.findall(r'[a-zA-Z0-9]+', cleaned.lower()))
        stop_words: Set[str] = {
            "buy", "purchase", "under", "within", "find", "order", "of", "a",
            "an", "the", "in", "to", "for", "please", "item", "product", "from",
            "details", "sku", "price", "with", "and", "is", "merchant", "inch", "hd"
        }
        return tokens - stop_words

    def compute_lexical_drift(self, user_intent: str, sku: str) -> float:
        words_intent = self._tokenize(user_intent)
        words_sku = self._tokenize(sku)

        # 1. Broad Category Definitions
        categories = {
            "laptop": {"laptop", "ultrabook", "notebook", "computer", "xps", "thinkpad", "macbook", "dev"},
            "chair": {"chair", "recliner", "seat", "seating", "ergonomic", "mesh"},
            "monitor": {"monitor", "display", "screen", "panel", "4k", "2k", "qhd"},
            "peripherals": {"soundbar", "audio", "keyboard", "rgb", "gift", "voucher", "desk"}
        }

        intent_category = None
        for cat_name, cat_keywords in categories.items():
            if bool(words_intent.intersection(cat_keywords)):
                intent_category = cat_name
                break

        sku_category = None
        for cat_name, cat_keywords in categories.items():
            if bool(words_sku.intersection(cat_keywords)):
                sku_category = cat_name
                break

        # A. Category Disparity (e.g. Chair -> Desk, Monitor -> Soundbar, Laptop -> Voucher) -> BLOCK
        if intent_category and sku_category and intent_category != sku_category:
            return 0.85

        # B. Direct Product Overlap -> Clean ALLOW
        intersection = words_intent.intersection(words_sku)
        overlap_ratio = len(intersection) / len(words_intent) if words_intent else 0.0

        if overlap_ratio >= 0.30:
            return 0.05

        # C. Same Category but Different Model (e.g. Dell XPS -> ThinkPad, Mesh Chair -> Leather Recliner) -> HITL Step-Up
        if intent_category and sku_category and intent_category == sku_category:
            return 0.50

        return 0.50

    async def compute_drift(self, user_intent: str, proposed_tool_payload: Dict[str, Any] | str) -> float:
        # Deterministic classification is insusceptible to remote API rate limits.
        if isinstance(proposed_tool_payload, str):
            sku = proposed_tool_payload
            amount = None
            quantity = 1
        else:
            sku = str(proposed_tool_payload.get("product_sku", ""))
            amount = proposed_tool_payload.get("amount_inr")
            quantity = proposed_tool_payload.get("quantity", 1)

        drift = self.compute_lexical_drift(user_intent, sku)
        budget_match = re.search(r"(?:under|below|within|less than)\s*(?:₹|inr\s*)?([\d,]+)", user_intent, re.IGNORECASE)
        if budget_match and amount is not None and float(amount) > float(budget_match.group(1).replace(",", "")):
            drift = max(drift, 0.85)
        quantity_match = re.search(r"(?:buy|order|purchase)\s+(\d+)\b", user_intent, re.IGNORECASE)
        requested_quantity = int(quantity_match.group(1)) if quantity_match else 1
        if quantity != requested_quantity:
            drift = max(drift, 0.85 if quantity > requested_quantity else 0.50)
        return min(1.0, drift)

vector_drift_engine = LexicalCategoryDriftEngine()