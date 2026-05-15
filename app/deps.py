"""Authorization helpers."""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request

import db as database
from app.core.config import get_settings
from app.domain.models import Bill
from app.services import bill_store


def _host_token_from_request(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    xt = request.headers.get("x-host-token") or request.headers.get("X-Host-Token")
    if xt:
        return xt.strip()
    return None


def verify_host_access(request: Request, bill: Bill) -> None:
    token = _host_token_from_request(request)
    if not token and bill.id:
        token = request.cookies.get(f"divvy_host_{bill.id}")
    sess = request.cookies.get("divvy_session")
    uid = database.get_session_user_id(sess) if sess else None
    user_owns = bool(uid and bill.owner_user_id and bill.owner_user_id == uid)
    valid = bool(bill.host_token and token == bill.host_token)
    if valid or user_owns:
        return
    raise HTTPException(status_code=403, detail="Host authentication required")


def verify_admin(request: Request) -> dict:
    sess = request.cookies.get("divvy_session")
    uid = database.get_session_user_id(sess) if sess else None
    if not uid:
        raise HTTPException(status_code=401, detail="Sign in required")
    user = database.get_user_by_id(uid)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    email = (user.get("email") or "").lower()
    admins = get_settings().admin_emails
    is_admin = bool(user.get("is_admin")) or user.get("is_admin") == 1
    if email not in admins and not is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def get_bill_for_participant_token(participant_token: str) -> Bill:
    data = database.get_bill_by_participant_token(participant_token)
    if not data:
        raise HTTPException(status_code=404, detail="Bill not found")
    return Bill(**data)
