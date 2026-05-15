"""Public status endpoint."""

from fastapi import APIRouter

import db as database
from app.core.config import get_settings, ocr_engine_name

router = APIRouter(tags=["status"])


@router.get("/api/status")
async def get_status():
    s = get_settings()
    return {
        "status": "ok",
        "ocr_engine": s.ocr_engine,
        "ocr_engine_label": ocr_engine_name(s.ocr_engine),
        "openai_configured": s.use_openai,
        "gemini_configured": s.use_gemini,
        "storage_mode": database.get_storage_mode(),
        "auth": "magic_link_and_host_token",
    }
