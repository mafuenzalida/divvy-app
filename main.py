"""ASGI entrypoint for backwards compatibility (uvicorn main:app)."""

from app.main import app

__all__ = ["app"]
