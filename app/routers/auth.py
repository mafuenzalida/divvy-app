"""Magic-link auth and current user."""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

import db as database
from app.core.config import get_settings
from app.domain.schemas import RequestMagicLinkBody
from app.limiter import limiter
from app.services.mail import send_magic_link_email

router = APIRouter(tags=["auth"])


@router.post("/api/auth/request-magic-link")
@limiter.limit("5/minute")
async def request_magic_link(request: Request, body: RequestMagicLinkBody):
    email = body.email.strip().lower()
    if "@" not in email or len(email) > 254:
        raise HTTPException(status_code=400, detail="Invalid email")
    raw = secrets.token_urlsafe(32)
    database.store_magic_link(email, raw, ttl_seconds=900)
    s = get_settings()
    link = f"{s.base_url.rstrip('/')}/api/auth/callback?token={raw}"
    ok = send_magic_link_email(email, link)
    if not ok and not s.mail_api_key:
        raise HTTPException(
            status_code=503,
            detail="Email is not configured (set MAIL_API_KEY and MAIL_FROM).",
        )
    return {"status": "sent" if ok else "queued", "detail": None if ok else "mail_failed"}


@router.get("/api/auth/callback")
async def auth_callback(token: str):
    email = database.consume_magic_link(token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired link")
    s = get_settings()
    admins = s.admin_emails
    user = database.get_user_by_email(email) or database.create_user(
        email, is_admin=(email in admins)
    )
    sess = database.create_session(user["id"])
    exp = datetime.now(timezone.utc) + timedelta(days=14)
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie(
        key="divvy_session",
        value=sess,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
        expires=exp.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        path="/",
    )
    return resp


@router.post("/api/auth/logout")
async def logout():
    r = JSONResponse({"status": "logged_out"})
    r.delete_cookie("divvy_session", path="/")
    return r


@router.get("/api/me")
async def me(request: Request):
    sess = request.cookies.get("divvy_session")
    uid = database.get_session_user_id(sess) if sess else None
    if not uid:
        return {"authenticated": False}
    user = database.get_user_by_id(uid)
    if not user:
        return {"authenticated": False}
    return {"authenticated": True, "user": {"id": user["id"], "email": user["email"]}}


@router.get("/api/me/bills")
async def my_bills(request: Request):
    sess = request.cookies.get("divvy_session")
    uid = database.get_session_user_id(sess) if sess else None
    if not uid:
        raise HTTPException(status_code=401, detail="Sign in required")
    rows = database.list_bills_by_owner(uid)
    bills = []
    for data in rows:
        bills.append(
            {
                "id": data.get("id"),
                "title": data.get("title"),
                "items_count": len(data.get("items") or []),
                "people_count": len(data.get("people") or []),
                "total": data.get("total"),
                "status": data.get("status"),
                "created_at": data.get("created_at"),
            }
        )
    bills.sort(key=lambda x: x.get("created_at", "") or "", reverse=True)
    return {"bills": bills}
