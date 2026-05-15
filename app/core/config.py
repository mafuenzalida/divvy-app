"""Application configuration from environment."""

import os
from functools import lru_cache


def _split_origins(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts or ["http://localhost:8000", "http://127.0.0.1:8000"]


@lru_cache
def get_settings():
    """Cached settings object (singleton per process)."""
    return Settings()


class Settings:
    def __init__(self) -> None:
        self.fintoc_username = os.getenv("FINTOC_USERNAME", "")
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY") or os.getenv(
            "GOOGLE_API_KEY"
        )
        self.base_url = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
        self.session_secret = os.getenv("SESSION_SECRET", "")
        self.mail_provider = os.getenv("MAIL_PROVIDER", "resend")
        self.mail_api_key = os.getenv("MAIL_API_KEY", "")
        self.mail_from = os.getenv("MAIL_FROM", "")
        self.admin_emails = {
            e.strip().lower()
            for e in os.getenv("ADMIN_EMAILS", "").split(",")
            if e.strip()
        }
        self.allowed_origins = _split_origins(os.getenv("ALLOWED_ORIGINS", ""))

        ok = (
            self.openai_api_key
            and len(self.openai_api_key) > 10
            and not self.openai_api_key.startswith("sk-your")
        )
        self.use_openai = bool(ok)
        gem = self.gemini_api_key and len(self.gemini_api_key) > 10
        self.use_gemini = bool(gem)
        if self.use_openai:
            self.ocr_engine = "openai"
        elif self.use_gemini:
            self.ocr_engine = "gemini"
        else:
            self.ocr_engine = "tesseract"


def ocr_engine_name(engine: str) -> str:
    return {
        "openai": "OpenAI Vision",
        "gemini": "Google Gemini (FREE)",
        "tesseract": "Tesseract (FREE)",
    }.get(engine, engine)
