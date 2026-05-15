"""In-memory bill cache and persistence helpers."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException

import db as database
from app.domain.models import Bill

LOG = logging.getLogger("divvy")

bills_storage: dict[str, Bill] = {}


def load_bills_from_storage() -> None:
    global bills_storage
    try:
        data = database.load_all_bills()
        for bill_id, bill_data in data.items():
            bills_storage[bill_id] = Bill(**bill_data)
    except Exception as e:
        LOG.exception("load_bills_failed error=%s", str(e))


def fetch_bill(bill_id: str, force_refresh: bool = False) -> Optional[Bill]:
    if force_refresh:
        bill_data = database.get_bill(bill_id)
        if bill_data:
            bill = Bill(**bill_data)
            bills_storage[bill_id] = bill
            return bill
        return None
    if bill_id in bills_storage:
        return bills_storage[bill_id]
    bill_data = database.get_bill(bill_id)
    if bill_data:
        bill = Bill(**bill_data)
        bills_storage[bill_id] = bill
        return bill
    return None


def refresh_bill_from_db(bill_id: str) -> Optional[Bill]:
    return fetch_bill(bill_id, force_refresh=True)


def persist_bill(bill: Bill, expected_version: Optional[int] = None) -> Bill:
    """Write bill to DB then cache. Optional optimistic version check."""
    d = bill.model_dump()
    try:
        database.save_bill_with_version(bill.id, d, expected_version)
    except ValueError as e:
        if "version_conflict" in str(e):
            raise HTTPException(
                status_code=409,
                detail="Bill was updated elsewhere; refresh and retry.",
            ) from e
        raise
    fresh = database.get_bill(bill.id)
    if not fresh:
        raise RuntimeError("bill_missing_after_save")
    bill = Bill(**fresh)
    bills_storage[bill.id] = bill
    return bill


def persist_bill_no_version(bill: Bill) -> Bill:
    """Save without optimistic check (server-only paths)."""
    database.save_bill(bill.id, bill.model_dump())
    fresh = database.get_bill(bill.id)
    if not fresh:
        raise RuntimeError("bill_missing_after_save")
    bill = Bill(**fresh)
    bills_storage[bill.id] = bill
    return bill


def recalculate_bill_totals(bill: Bill) -> Bill:
    bill.subtotal = sum(item.price * item.quantity for item in bill.items)
    if bill.tip_percent > 0:
        bill.tip = bill.subtotal * (bill.tip_percent / 100)
    bill.total = bill.subtotal + bill.tax + bill.tip
    return bill
