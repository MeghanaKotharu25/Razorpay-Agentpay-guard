from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    OPENROUTER_API_KEY: str = "mock-key"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    PRIMARY_MODEL: str = "meta-llama/llama-3.3-70b-instruct:free"
    GUARD_MODEL: str = "meta-llama/llama-3.3-70b-instruct:free"

    RAZORPAY_KEY_ID: str = "rzp_test_placeholder"
    RAZORPAY_KEY_SECRET: str = "rzp_secret_placeholder"

    # Set system-level ceiling to 1 Lakh INR to support standard laptops
    MAX_SESSION_SPEND_INR: float = 100000.0
    MAX_DAILY_SPEND_INR: float = 250000.0
    ALLOWED_CURRENCY: str = "INR"
    ALLOWED_ORIGINS: List[str] = ["http://localhost:5173"]
    ALLOWED_MERCHANTS: List[str] = [
        "merchant_tech_mart",
        "merchant_croma_direct",
        "merchant_official_store",
        "merchant_office_supplies_co"
    ]
    
    DATABASE_PATH: str = "audit_vault.db"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()