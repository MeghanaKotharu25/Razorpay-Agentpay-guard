from typing import List, Dict, Any
from pydantic import BaseModel, Field
from app.integrations.mock_merchant import search_merchant_catalog, get_product_by_sku

class CatalogSearchInput(BaseModel):
    query: str = Field(description="Search keywords for products, brands, or categories")

class PurchaseProposalInput(BaseModel):
    merchant_id: str = Field(description="Verified ID of the selling merchant")
    amount_inr: float = Field(description="Total calculated transaction amount in INR")
    currency: str = Field(default="INR", description="Three-letter currency code")
    product_sku: str = Field(description="Unique product SKU")
    quantity: int = Field(default=1, description="Number of units to purchase")

def search_catalog_tool(query: str) -> List[Dict[str, Any]]:
    """Searches the merchant catalog for relevant matching products."""
    return search_merchant_catalog(query)

def get_product_details_tool(sku: str) -> Dict[str, Any]:
    """Retrieves full specification and stock metadata for a given SKU."""
    product = get_product_by_sku(sku)
    if not product:
        return {"error": f"Product with SKU '{sku}' not found."}
    return product