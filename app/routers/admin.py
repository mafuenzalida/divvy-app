"""Admin-only maintenance."""

from fastapi import APIRouter, Request

from app.deps import verify_admin
from app.services import bill_store
import db as database

router = APIRouter(tags=["admin"])


@router.get("/api/admin/bills")
async def admin_list_bills(request: Request):
    verify_admin(request)
    return {"bills": database.list_all_bill_summaries()}


@router.post("/api/admin/refresh-all-bills")
async def refresh_all_bills_cache(request: Request):
    verify_admin(request)
    bill_store.load_bills_from_storage()
    return {
        "status": "refreshed",
        "bills_count": len(bill_store.bills_storage),
        "message": "All bills refreshed from database",
    }
