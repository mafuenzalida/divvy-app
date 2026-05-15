"""Participant APIs (participant token only)."""

from fastapi import APIRouter, HTTPException, Request

from app.core.config import get_settings
from app.limiter import limiter
from app.deps import get_bill_for_participant_token
from app.domain.schemas import JoinBillRequest, ParticipantMarkPaidRequest, SelfAssignRequest
from app.services import bill_store
from app.services.money import (
    compute_person_totals_minor,
    from_minor,
    fintoc_link_amount_minor,
)
from app.services.splits import set_item_claim_units

router = APIRouter(tags=["participant"])


@router.get("/api/p/t/{participant_token}")
async def get_bill_for_participant(participant_token: str):
    bill = get_bill_for_participant_token(participant_token)
    bill = bill_store.fetch_bill(bill.id, force_refresh=True) or bill
    minor = compute_person_totals_minor(bill)
    person_totals = {p: from_minor(m) for p, m in minor.items()}
    fintoc_user = bill.fintoc_username or get_settings().fintoc_username
    payment_links = {}
    if fintoc_user:
        for person, m in minor.items():
            if m > 0:
                amt = fintoc_link_amount_minor(m)
                payment_links[person] = f"https://fintoc.me/{fintoc_user}/{amt}"
    return {
        "bill": bill,
        "person_totals": person_totals,
        "person_totals_minor": minor,
        "payment_links": payment_links,
    }


@router.post("/api/p/t/{participant_token}/join")
@limiter.limit("15/minute")
async def join_bill(participant_token: str, request: Request, body: JoinBillRequest):
    bill = get_bill_for_participant_token(participant_token)
    bill = bill_store.fetch_bill(bill.id, force_refresh=True) or bill
    if bill.locked:
        raise HTTPException(status_code=403, detail="La cuenta está bloqueada")
    if bill.status == "closed":
        raise HTTPException(status_code=403, detail="La cuenta está cerrada")
    person_name = body.person_name.strip()
    if not person_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    if person_name in bill.people:
        raise HTTPException(status_code=400, detail="Name already exists")
    bill.people.append(person_name)
    bill = bill_store.persist_bill(bill, None)
    return {"status": "joined", "person_name": person_name, "bill": bill}


@router.post("/api/p/t/{participant_token}/self-assign")
async def self_assign_item(participant_token: str, body: SelfAssignRequest):
    bill = get_bill_for_participant_token(participant_token)
    bill = bill_store.fetch_bill(bill.id, force_refresh=True) or bill
    if bill.locked:
        raise HTTPException(status_code=403, detail="La cuenta está bloqueada")
    if bill.status == "closed":
        raise HTTPException(status_code=403, detail="La cuenta está cerrada")
    item = next((i for i in bill.items if i.id == body.item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if body.person_name not in bill.people:
        raise HTTPException(status_code=400, detail="Person not in bill")
    if body.assigned:
        set_item_claim_units(item, body.person_name, body.units)
    else:
        set_item_claim_units(item, body.person_name, 0)
    bill = bill_store.persist_bill(bill, None)
    return {"status": "updated", "bill": bill}


@router.post("/api/p/t/{participant_token}/mark-paid")
async def participant_mark_paid(participant_token: str, body: ParticipantMarkPaidRequest):
    bill = get_bill_for_participant_token(participant_token)
    bill = bill_store.fetch_bill(bill.id, force_refresh=True) or bill
    name = body.person_name.strip()
    if not name or name not in bill.people:
        raise HTTPException(status_code=400, detail="Person not in bill")
    if body.paid:
        if name not in bill.paid_by:
            bill.paid_by.append(name)
    else:
        if name in bill.paid_by:
            bill.paid_by.remove(name)
    bill = bill_store.persist_bill(bill, None)
    return bill
