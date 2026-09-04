import os
import secrets
import time
from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    OPENROUTER_API_KEY: str = "mock-key"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    PRIMARY_MODEL: str = "meta-llama/llama-3.3-70b-instruct:free"
    GUARD_MODEL: str = "meta-llama/llama-3.3-70b-instruct:free"

    RAZORPAY_KEY_ID: str = "rzp_test_placeholder"
    RAZORPAY_KEY_SECRET: str = "rzp_secret_placeholder"

    MAX_SESSION_SPEND_INR: float = 10000.0
    MAX_ORDER_AMOUNT_INR: float = 100000.0
    MAX_DAILY_SPEND_INR: float = 250000.0
    MAX_AUTONOMOUS_TRANSACTION_INR: float = 2000.0
    AUDIT_HMAC_SECRET: Optional[str] = None
    AUDIT_SECRET_PATH: str = ".audit_hmac_secret"
    AP2_SIGNING_SECRET: Optional[str] = None
    AP2_SECRET_PATH: str = ".ap2_signing_secret"
    IDEMPOTENCY_TTL_SECONDS: int = 600
    API_AUTH_KEY: str = "demo-agentpay-key"
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

    def model_post_init(self, __context: object) -> None:
        self.AUDIT_HMAC_SECRET = self._resolve_secret(
            self.AUDIT_HMAC_SECRET, self.AUDIT_SECRET_PATH, "AUDIT_HMAC_SECRET"
        )
        self.AP2_SIGNING_SECRET = self._resolve_secret(
            self.AP2_SIGNING_SECRET, self.AP2_SECRET_PATH, "AP2_SIGNING_SECRET"
        )

    @staticmethod
    def _resolve_secret(configured: Optional[str], path_value: str, name: str) -> str:
        configured = (configured or "").strip()
        if configured:
            if configured in {"agentpay-demo-audit-secret-change-me", "agentpay_demo_shared_secret"}:
                raise ValueError(f"{name} must not use a public demo value")
            return configured

        secret_path = Path(path_value)
        try:
            configured = secret_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            lock_path = Path(f"{secret_path}.lock")
            try:
                lock_descriptor = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                for _ in range(100):
                    configured = secret_path.read_text(encoding="utf-8").strip() if secret_path.exists() else ""
                    if configured:
                        break
                    time.sleep(0.01)
            else:
                try:
                    configured = secrets.token_urlsafe(48)
                    temporary_path = Path(f"{secret_path}.{os.getpid()}.tmp")
                    temporary_path.write_text(configured, encoding="utf-8")
                    os.chmod(temporary_path, 0o600)
                    os.replace(temporary_path, secret_path)
                finally:
                    os.close(lock_descriptor)
                    lock_path.unlink(missing_ok=True)
        if not configured:
            raise ValueError(f"{name} could not be initialized")
        return configured

settings = Settings()