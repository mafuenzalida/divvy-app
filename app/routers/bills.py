"""Host-authenticated bill APIs."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request

from app.core.config import get_settings
from app.deps import verify_host_access
from app.domain.models import Bill, BillItem, new_bill_id, new_item_id
from app.domain.schemas import (
    AddItemRequest,
    AddPersonRequest,
    AssignItemRequest,
    ClaimBillBody,
    CreateBillRequest,
    LockBillRequest,
    MarkPaidRequest,
    RestoreBillRequest,
    SetBillStatusRequest,
    SplitBillEquallyRequest,
    UpdateBillTitleRequest,
    UpdateFintocUsernameRequest,
    UpdateTipTaxRequest,
)
from app.services import bill_store
from app.services.money import (
    compute_person_totals_minor,
    from_minor,
    fintoc_link_amount_minor,
)
from app.services.splits import set_item_claim_units

router = APIRouter(tags=["bills"])


def _urls(bill: Bill) -> dict[str, str]:
    base = get_settings().base_url.rstrip("/")
    return {
        "host_edit_url": f"{base}/edit/{bill.host_token}",
        "participant_url": f"{base}/b/{bill.participant_token}",
    }


@router.post("/api/create-bill")
async def create_bill(request: Request, body: CreateBillRequest = CreateBillRequest()):
    title = (body.title or "").strip() or "Boleta"
    bill = Bill(
        id=new_bill_id(),
        title=title[:80],
        items=[],
        subtotal=0.0,
        tax=0.0,
        tip=0.0,
        tip_percent=0.0,
        total=0.0,
        people=[],
        paid_by=[],
        locked=False,
        status="draft",
        created_at=datetime.now().isoformat(),
        host_token="",
        participant_token="",
        owner_user_id=None,
        version=0,
    )
    bill = bill_store.persist_bill(bill, None)
    out = bill.model_dump()
    out.update(_urls(bill))
    return out


@router.get("/api/bill/{bill_id}")
async def get_bill(bill_id: str, request: Request, fresh: bool = True):
    bill = bill_store.fetch_bill(bill_id, force_refresh=fresh)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    return bill


@router.post("/api/restore-bill")
async def restore_bill(request: Request, payload: RestoreBillRequest):
    bill = payload.bill
    existing = bill_store.fetch_bill(bill.id, force_refresh=True)
    if existing:
        verify_host_access(request, existing)
        bill.people = existing.people if existing.people else bill.people
        db_by_id = {i.id: i for i in existing.items}
        for client_item in bill.items:
            if client_item.id in db_by_id:
                db_item = db_by_id[client_item.id]
                client_item.claims = dict(db_item.claims)
                client_item.assigned_to = []
    bill = bill_store.recalculate_bill_totals(bill)
    if bill.paid_by is None:
        bill.paid_by = []
    if not bill.title:
        bill.title = "Boleta"
    bill = bill_store.persist_bill(bill, payload.expected_version)
    return {"status": "restored", "bill_id": bill.id, "bill": bill}


@router.post("/api/update-title")
async def update_bill_title(request: Request, req: UpdateBillTitleRequest):
    bill = bill_store.fetch_bill(req.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    bill.title = title[:80]
    bill = bill_store.persist_bill(bill, req.version)
    return bill


@router.post("/api/update-fintoc-username")
async def update_fintoc_username(request: Request, req: UpdateFintocUsernameRequest):
    bill = bill_store.fetch_bill(req.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    bill.fintoc_username = req.fintoc_username.strip().lstrip("@")
    bill = bill_store.persist_bill(bill, req.version)
    return bill


@router.post("/api/add-person")
async def add_person(request: Request, req: AddPersonRequest):
    bill = bill_store.fetch_bill(req.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")
    if req.person_name not in bill.people:
        bill.people.append(req.person_name)
    bill = bill_store.persist_bill(bill, req.version)
    return bill


@router.post("/api/remove-person")
async def remove_person(request: Request, req: AddPersonRequest):
    bill = bill_store.fetch_bill(req.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")
    if req.person_name in bill.people:
        bill.people.remove(req.person_name)
        for item in bill.items:
            item.claims.pop(req.person_name, None)
        if req.person_name in bill.paid_by:
            bill.paid_by.remove(req.person_name)
    bill = bill_store.persist_bill(bill, req.version)
    return bill


@router.post("/api/assign-item")
async def assign_item(request: Request, req: AssignItemRequest):
    bill = bill_store.fetch_bill(req.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")
    item = next((i for i in bill.items if i.id == req.item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    current = float(item.claims.get(req.person_name, 0) or 0)
    if req.units is not None:
        set_item_claim_units(item, req.person_name, req.units)
    elif current > 1e-12:
        set_item_claim_units(item, req.person_name, 0)
    else:
        set_item_claim_units(item, req.person_name, 1.0)
    bill = bill_store.persist_bill(bill, req.version)
    return bill


@router.post("/api/split-bill-equally")
async def split_bill_equally(request: Request, req: SplitBillEquallyRequest):
    bill = bill_store.fetch_bill(req.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")
    n = len(bill.people)
    if n == 0:
        raise HTTPException(status_code=400, detail="Add people first")
    per = 1.0 / float(n)
    for item in bill.items:
        item.claims = {}
        share = float(item.quantity) * per
        for p in bill.people:
            item.claims[p] = share
    bill = bill_store.persist_bill(bill, req.version)
    return bill


@router.post("/api/update-tip-tax")
async def update_tip_tax(request: Request, req: UpdateTipTaxRequest):
    bill = bill_store.fetch_bill(req.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")
    if req.tip_percent is not None:
        bill.tip_percent = req.tip_percent
        bill.tip = bill.subtotal * (req.tip_percent / 100)
    if req.tax is not None:
        bill.tax = req.tax
    bill.total = bill.subtotal + bill.tax + bill.tip
    bill = bill_store.persist_bill(bill, req.version)
    return bill


@router.post("/api/add-item")
async def add_item(request: Request, req: AddItemRequest):
    bill = bill_store.fetch_bill(req.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")
    new_item = BillItem(
        id=new_item_id(),
        name=req.name,
        price=req.price,
        quantity=req.quantity,
        claims={},
    )
    bill.items.append(new_item)
    bill.subtotal += new_item.price * new_item.quantity
    if bill.tip_percent > 0:
        bill.tip = bill.subtotal * (bill.tip_percent / 100)
    bill.total = bill.subtotal + bill.tax + bill.tip
    bill = bill_store.persist_bill(bill, req.version)
    return bill


@router.delete("/api/item/{bill_id}/{item_id}")
async def delete_item(
    bill_id: str,
    item_id: str,
    request: Request,
    version: int | None = None,
):
    bill = bill_store.fetch_bill(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")
    item = next((i for i in bill.items if i.id == item_id), None)
    if item:
        bill.subtotal -= item.price * item.quantity
        bill.items = [i for i in bill.items if i.id != item_id]
        if bill.tip_percent > 0:
            bill.tip = bill.subtotal * (bill.tip_percent / 100)
        bill.total = bill.subtotal + bill.tax + bill.tip
    bill = bill_store.persist_bill(bill, version)
    return bill


@router.post("/api/lock-bill")
async def lock_bill(request: Request, req: LockBillRequest):
    bill = bill_store.fetch_bill(req.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    bill.locked = req.locked
    bill = bill_store.persist_bill(bill, req.version)
    return bill


@router.post("/api/mark-paid")
async def mark_paid(request: Request, req: MarkPaidRequest):
    bill = bill_store.fetch_bill(req.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    if req.paid:
        if req.person_name not in bill.paid_by:
            bill.paid_by.append(req.person_name)
    else:
        if req.person_name in bill.paid_by:
            bill.paid_by.remove(req.person_name)
    bill = bill_store.persist_bill(bill, req.version)
    return bill


@router.post("/api/bill/{bill_id}/status")
async def set_bill_status(bill_id: str, request: Request, req: SetBillStatusRequest):
    if req.status not in ["draft", "ready", "closed"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    bill = bill_store.fetch_bill(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    bill.status = req.status
    if req.status in ["ready", "closed"]:
        bill.locked = True
    elif req.status == "draft":
        bill.locked = False
    bill = bill_store.persist_bill(bill, req.version)
    return {"status": "updated", "bill": bill}


@router.post("/api/refresh-bill/{bill_id}")
async def refresh_bill_cache(bill_id: str, request: Request):
    bill = bill_store.refresh_bill_from_db(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
    return {"status": "refreshed", "bill": bill}


@router.get("/api/calculate-splits/{bill_id}")
async def calculate_splits(bill_id: str, request: Request):
    bill = bill_store.fetch_bill(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    verify_host_access(request, bill)
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
        "bill_id": bill_id,
        "person_totals": person_totals,
        "person_totals_minor": minor,
        "payment_links": payment_links,
        "bill_total": bill.total,
        "assigned_total": sum(person_totals.values()),
    }


@router.post("/api/bills/{bill_id}/claim")
async def claim_bill(bill_id: str, request: Request, body: ClaimBillBody):
    import db as database

    sess = request.cookies.get("divvy_session")
    uid = database.get_session_user_id(sess) if sess else None
    if not uid:
        raise HTTPException(status_code=401, detail="Sign in required")
    bill = bill_store.fetch_bill(bill_id, force_refresh=True)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    if bill.host_token != body.host_token:
        raise HTTPException(status_code=403, detail="Invalid host token")
    bill.owner_user_id = uid
    bill = bill_store.persist_bill(bill, None)
    return {"status": "claimed", "bill": bill}
