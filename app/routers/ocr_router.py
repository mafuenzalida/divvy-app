"""Receipt scan upload."""

import io
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from PIL import Image

from app.core.config import get_settings
from app.domain.models import Bill, BillItem, new_bill_id, new_item_id
from app.limiter import limiter
from app.services import bill_store
from app.services import ocr as ocr_service

router = APIRouter(tags=["ocr"])

MAX_UPLOAD_BYTES = 8 * 1024 * 1024


@router.post("/api/scan-bill")
@limiter.limit("10/minute")
async def scan_bill(request: Request, file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    image_bytes = await file.read()
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 8MB)")
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        if getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) > 1:
            raise HTTPException(status_code=400, detail="Animated images not supported")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid image file") from e

    s = get_settings()
    try:
        if s.ocr_engine == "openai":
            image_base64 = ocr_service.encode_image_to_base64(image_bytes)
            parsed_data = ocr_service.parse_bill_with_openai(image_base64)
        elif s.ocr_engine == "gemini":
            parsed_data = ocr_service.parse_bill_with_gemini(image_bytes)
        else:
            parsed_data = ocr_service.parse_bill_with_tesseract(image_bytes)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing image: {e}") from e

    bill_id = new_bill_id()
    items = [
        BillItem(
            id=new_item_id(),
            name=item["name"],
            price=float(item["price"]),
            quantity=int(item.get("quantity", 1)) or 1,
            claims={},
        )
        for item in parsed_data.get("items", [])
    ]
    bill = Bill(
        id=bill_id,
        title="Boleta",
        items=items,
        subtotal=float(
            parsed_data.get("subtotal", sum(i.price * i.quantity for i in items))
        ),
        tax=float(parsed_data.get("tax", 0)),
        tip=float(parsed_data.get("tip", 0)),
        tip_percent=0.0,
        total=float(parsed_data.get("total", 0)),
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
    base = s.base_url.rstrip("/")
    out = bill.model_dump()
    out["host_edit_url"] = f"{base}/edit/{bill.host_token}"
    out["participant_url"] = f"{base}/b/{bill.participant_token}"
    return out
