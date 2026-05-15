"""Transactional email (Resend)."""

import logging
from typing import Optional

import httpx

from app.core.config import get_settings

LOG = logging.getLogger("divvy")


def send_magic_link_email(to_email: str, link_url: str) -> bool:
    s = get_settings()
    if not s.mail_api_key or s.mail_provider.lower() != "resend":
        LOG.warning("mail_not_configured provider=%s", s.mail_provider)
        return False
    try:
        r = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {s.mail_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": s.mail_from or "Divvy <onboarding@resend.dev>",
                "to": [to_email],
                "subject": "Sign in to Divvy",
                "html": f'<p>Click to sign in:</p><p><a href="{link_url}">{link_url}</a></p>',
            },
            timeout=15.0,
        )
        if r.status_code >= 400:
            LOG.error("resend_error status=%s body=%s", r.status_code, r.text)
            return False
        return True
    except Exception as e:
        LOG.exception("send_mail_failed error=%s", str(e))
        return False
