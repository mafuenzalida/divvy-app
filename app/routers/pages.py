"""HTML pages and host bootstrap redirects."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

import db as database
from app.core.config import get_settings

router = APIRouter(tags=["pages"])


@router.get("/", response_class=None)
async def serve_frontend():
    return FileResponse("static/index.html")


@router.get("/bill/{bill_id}", response_class=None)
async def legacy_participant_redirect(bill_id: str):
    """Old links: redirect to home with hint."""
    return RedirectResponse(url=f"/?legacy_bill={bill_id}", status_code=302)


@router.get("/b/{participant_token}", response_class=None)
async def serve_participant_by_token(participant_token: str):
    return FileResponse("static/participant.html")


@router.get("/edit/{host_token}", response_class=None)
async def host_edit_landing(host_token: str):
    data = database.get_bill_by_host_token(host_token)
    if not data:
        raise HTTPException(status_code=404, detail="Invalid host link")
    bill_id = data["id"]
    resp = RedirectResponse(url=f"/?bill={bill_id}", status_code=302)
    exp = datetime.now(timezone.utc) + timedelta(days=90)
    resp.set_cookie(
        key=f"divvy_host_{bill_id}",
        value=host_token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 90,
        expires=exp.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        path="/",
    )
    return resp
