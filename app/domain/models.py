"""Bill domain models."""

from __future__ import annotations

import secrets
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


class BillItem(BaseModel):
    id: str
    name: str
    price: float
    quantity: int = 1
    assigned_to: list[str] = Field(default_factory=list)
    claims: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_assigned(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw_claims = data.get("claims")
        assigned = data.get("assigned_to") or []
        claims: dict[str, float] = {}
        if raw_claims is not None and isinstance(raw_claims, dict):
            for k, v in raw_claims.items():
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if fv > 1e-12:
                    claims[str(k)] = fv
        if sum(claims.values()) <= 1e-12 and assigned:
            cnt: dict[str, int] = {}
            for p in assigned:
                s = str(p)
                cnt[s] = cnt.get(s, 0) + 1
            claims = {k: float(v) for k, v in cnt.items()}
        data["claims"] = claims
        data["assigned_to"] = []
        return data


class Bill(BaseModel):
    id: str
    title: str = "Boleta"
    items: list[BillItem]
    subtotal: float
    tax: float = 0.0
    tip: float = 0.0
    tip_percent: float = 0.0
    total: float
    people: list[str] = []
    paid_by: list[str] = []
    locked: bool = False
    status: str = "draft"
    created_at: str
    fintoc_username: str = ""
    host_token: str = ""
    participant_token: str = ""
    owner_user_id: Optional[str] = None
    version: int = 0


def new_bill_id() -> str:
    return secrets.token_urlsafe(16)


def new_item_id() -> str:
    return secrets.token_hex(4)
