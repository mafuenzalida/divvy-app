"""
Divvy - Bill Splitting App
A beautiful app to scan bills, split expenses, and generate payment links.
"""

import os
import json
import base64
import uuid
import re
import io
from typing import Any, Optional
from datetime import datetime

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    WebSocket,
    Request,
    Depends,
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
import asyncio
from pydantic import BaseModel, Field, model_validator
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

# Import database adapter
import db as database

app = FastAPI(title="Divvy", description="Bill Splitting Made Beautiful")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for bills (loaded from file on startup)
bills_storage: dict = {}

# Fintoc configuration (can be overridden per-bill)
FINTOC_USERNAME = os.getenv("FINTOC_USERNAME", "")

# App password protection (optional)
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

# Check available API keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

USE_OPENAI = (
    OPENAI_API_KEY
    and len(OPENAI_API_KEY) > 10
    and not OPENAI_API_KEY.startswith("sk-your")
)
USE_GEMINI = GEMINI_API_KEY and len(GEMINI_API_KEY) > 10

# Determine which OCR engine to use
if USE_OPENAI:
    OCR_ENGINE = "openai"
elif USE_GEMINI:
    OCR_ENGINE = "gemini"
else:
    OCR_ENGINE = "tesseract"


class BillItem(BaseModel):
    id: str
    name: str
    price: float
    quantity: int = 1
    assigned_to: list[str] = Field(default_factory=list)  # legacy; cleared on load
    claims: dict[str, float] = Field(default_factory=dict)  # person -> units (float, sum <= quantity)

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
    paid_by: list[str] = []  # People who have paid
    locked: bool = False  # When locked, no modifications allowed
    status: str = "draft"  # draft, ready, closed
    created_at: str
    fintoc_username: str = ""  # Fintoc username for payment links


def item_other_claims_sum(item: BillItem, person_name: str) -> float:
    return sum(u for p, u in item.claims.items() if p != person_name)


def item_claim_weight_sum(item: BillItem) -> float:
    return sum(float(w) for w in item.claims.values() if w > 1e-12)


def set_item_claim_units(item: BillItem, person_name: str, units: float) -> None:
    """Set claim weight/units. For quantity>1, sum(claims) <= quantity. For quantity==1, weights
    are only capped at 0+; if sum(weights) <= 1 each weight is a fraction of the line, if sum > 1
    weights split the line proportionally (several people can each use 1)."""
    qty = float(item.quantity) if item.quantity else 1.0
    units = max(0.0, float(units))
    if qty <= 1.0 + 1e-12:
        if units <= 1e-12:
            item.claims.pop(person_name, None)
        else:
            item.claims[person_name] = units
        return
    others = item_other_claims_sum(item, person_name)
    max_for_person = max(0.0, qty - others)
    if units > max_for_person:
        units = max_for_person
    if units <= 1e-12:
        item.claims.pop(person_name, None)
    else:
        item.claims[person_name] = units


def person_line_dollar_share(item: BillItem, person_name: str) -> float:
    """Dollar share for this line. quantity>1: line_total * (u/qty). quantity==1: if sum(claims)<=1,
    absolute fraction u of the line; if sum>1, split line by relative weights u/sum(claims)."""
    u = item.claims.get(person_name)
    if u is None or u <= 1e-12:
        return 0.0
    u = float(u)
    line_total = item.price * item.quantity
    qty = float(item.quantity) if item.quantity else 1.0
    if qty > 1.0 + 1e-12:
        return line_total * (u / qty)
    s = item_claim_weight_sum(item)
    if s <= 1.0 + 1e-9:
        return line_total * u
    return line_total * (u / s)


def load_bills_from_storage():
    """Load bills from persistent storage (Turso or local file)."""
    global bills_storage
    try:
        data = database.load_all_bills()
        for bill_id, bill_data in data.items():
            bills_storage[bill_id] = Bill(**bill_data)
    except Exception as e:
        print(f"Error loading bills: {e}")


def save_bill(bill, force_refresh_first: bool = False):
    """Save a single bill to storage.

    CRITICAL: Saves to database FIRST, then updates cache only on success.
    This ensures data integrity - if DB save fails, cache is not updated.

    Args:
        bill: The Bill object to save
        force_refresh_first: If True, fetch latest from DB before saving (prevents overwriting concurrent changes)
    """
    # If force_refresh_first, get the latest version from DB to prevent overwriting concurrent changes
    if force_refresh_first:
        bill_data = database.get_bill(bill.id)
        if bill_data:
            # Merge with current changes - this is a simple approach
            # For more complex scenarios, consider version numbers or optimistic locking
            # For now, we'll save the current bill as-is
            # The caller should handle merging if needed
            pass

    # CRITICAL: Save to database FIRST
    try:
        database.save_bill(bill.id, bill.model_dump())
    except Exception as e:
        # If DB save fails, DO NOT update cache - this ensures data integrity
        error_msg = f"❌ CRITICAL: Failed to save bill {bill.id} to database: {e}"
        print(error_msg)
        raise HTTPException(status_code=500, detail=error_msg) from e

    # Only update cache AFTER successful DB save
    bills_storage[bill.id] = bill
    print(
        f"💾 Saved bill {bill.id}: {len(bill.people)} people, {len(bill.items)} items"
    )


def fetch_bill(bill_id: str, force_refresh: bool = False) -> Optional[Bill]:
    """Get a bill - try memory first, then fetch from DB if not found.

    Args:
        bill_id: The bill ID to fetch
        force_refresh: If True, always fetch from database (bypasses cache)
    """
    # If force refresh, always get from database
    if force_refresh:
        bill_data = database.get_bill(bill_id)
        if bill_data:
            bill = Bill(**bill_data)
            bills_storage[bill_id] = bill  # Update cache
            print(f"🔄 Refreshed bill {bill_id} from database")
            return bill
        return None

    # Try memory cache first
    if bill_id in bills_storage:
        return bills_storage[bill_id]

    # Not in memory - try fetching from database
    bill_data = database.get_bill(bill_id)
    if bill_data:
        bill = Bill(**bill_data)
        bills_storage[bill_id] = bill  # Cache it
        print(f"📥 Loaded bill {bill_id} from database (was not in memory)")
        return bill

    return None


def refresh_bill_from_db(bill_id: str) -> Optional[Bill]:
    """Force refresh a bill from database and update cache."""
    return fetch_bill(bill_id, force_refresh=True)


# Load bills on startup
load_bills_from_storage()


class AssignItemRequest(BaseModel):
    bill_id: str
    item_id: str
    person_name: str
    # If set, exact units for this person on this item. If omitted, toggle: add 1 or clear all.
    units: Optional[float] = None


class AddPersonRequest(BaseModel):
    bill_id: str
    person_name: str


class UpdateTipTaxRequest(BaseModel):
    bill_id: str
    tip_percent: Optional[float] = None
    tax: Optional[float] = None


class UpdateBillTitleRequest(BaseModel):
    bill_id: str
    title: str


class UpdateFintocUsernameRequest(BaseModel):
    bill_id: str
    fintoc_username: str


class CreateBillRequest(BaseModel):
    title: Optional[str] = None


class AddItemRequest(BaseModel):
    bill_id: str
    name: str
    price: float
    quantity: int = 1


class LockBillRequest(BaseModel):
    bill_id: str
    locked: bool


class MarkPaidRequest(BaseModel):
    bill_id: str
    person_name: str
    paid: bool


class JoinBillRequest(BaseModel):
    bill_id: str
    person_name: str


class SelfAssignRequest(BaseModel):
    bill_id: str
    person_name: str
    item_id: str
    assigned: bool  # True to assign, False to unassign
    units: float = 1.0  # Units to claim (integers or fractions, e.g. 0.2 of quantity 1)


class SetBillStatusRequest(BaseModel):
    bill_id: str
    status: str  # draft, ready, closed


class SplitBillEquallyRequest(BaseModel):
    bill_id: str


class AuthRequest(BaseModel):
    password: str


def encode_image_to_base64(image_bytes: bytes) -> str:
    """Encode image bytes to base64 string."""
    return base64.b64encode(image_bytes).decode("utf-8")


def parse_bill_with_gemini(image_bytes: bytes) -> dict:
    """Use Google Gemini to parse bill image (FREE tier available)."""
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)

    # Create the model (using latest free model)
    model = genai.GenerativeModel("gemini-2.5-flash")

    # Prepare image
    image = Image.open(io.BytesIO(image_bytes))

    # Convert to RGB if necessary (handles RGBA, etc)
    if image.mode != "RGB":
        image = image.convert("RGB")

    prompt = """Look at this receipt/bill image and extract all the purchased items with their prices.

Return ONLY a valid JSON object (no markdown, no explanation) with this structure:
{
    "items": [
        {"name": "Item name", "price": 1000, "quantity": 1}
    ],
    "subtotal": 5000,
    "tax": 950,
    "tip": 0,
    "total": 5950
}

Rules:
- List every item you can see with its price
- For each item set "quantity" to the count sold (default 1). If the line shows "3 x Beer" or "2 Café", use 3 or 2 and set "price" to the UNIT price (line total ÷ quantity). If only a line total exists, use quantity 1 and that price.
- Prices must be numbers (integers or decimals)
- Include tax/IVA if shown
- Include tip/propina if shown
- Use 0 for unknown values
"""

    try:
        response = model.generate_content([prompt, image])

        # Check if response was blocked
        if not response.candidates:
            feedback = getattr(response, "prompt_feedback", None)
            raise ValueError(f"Gemini blocked the request: {feedback}")

        result_text = response.text

    except ValueError as e:
        if "blocked" in str(e).lower() or "empty" in str(e).lower():
            # Try with a simpler prompt
            simple_prompt = 'List all items from this receipt as JSON: {"items": [{"name": "...", "price": 0, "quantity": 1}], "total": 0}. Use quantity>1 when a line shows multiples; price = unit price.'
            response = model.generate_content([simple_prompt, image])
            if not response.candidates:
                raise ValueError(
                    "Gemini could not process this image. Try a clearer photo."
                )
            result_text = response.text
        else:
            raise

    # Clean up response - extract JSON if wrapped in markdown
    if "```json" in result_text:
        result_text = result_text.split("```json")[1].split("```")[0]
    elif "```" in result_text:
        result_text = result_text.split("```")[1].split("```")[0]

    parsed = json.loads(result_text.strip())

    # Ensure required fields exist
    if "items" not in parsed:
        parsed["items"] = []
    if "subtotal" not in parsed:
        parsed["subtotal"] = sum(
            item.get("price", 0) * item.get("quantity", 1) for item in parsed["items"]
        )
    if "tax" not in parsed:
        parsed["tax"] = 0
    if "tip" not in parsed:
        parsed["tip"] = 0
    if "total" not in parsed:
        parsed["total"] = parsed["subtotal"] + parsed["tax"] + parsed["tip"]

    return parsed


def parse_bill_with_tesseract(image_bytes: bytes) -> dict:
    """Use Tesseract OCR to parse bill image (FREE - no API key needed)."""
    import pytesseract

    # Open image
    image = Image.open(io.BytesIO(image_bytes))

    # Convert to grayscale for better OCR
    if image.mode != "L":
        image = image.convert("L")

    # Run OCR with Spanish + English
    text = pytesseract.image_to_string(image, lang="spa+eng")

    print(f"OCR Text:\n{text}")  # Debug output

    # Parse the text to extract items and prices
    items = []
    lines = text.strip().split("\n")

    # Common patterns for prices in Chilean/Spanish receipts
    price_patterns = [
        r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*$",  # Price at end of line
        r"\$\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)",  # $1.234 or $1234
        r"(\d+(?:[.,]\d+)?)\s*(?:CLP|clp)?$",  # Number with optional CLP
    ]

    subtotal = 0
    tax = 0
    tip = 0
    total = 0

    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        # Skip common header/footer lines
        skip_words = [
            "boleta",
            "factura",
            "rut",
            "fecha",
            "hora",
            "ticket",
            "gracias",
            "vuelva",
            "pronto",
            "direccion",
            "telefono",
            "www",
            "http",
        ]
        if any(word in line.lower() for word in skip_words):
            continue

        # Check for tax/tip/total lines
        line_lower = line.lower()

        # Try to extract price from line
        price_match = None
        for pattern in price_patterns:
            match = re.search(pattern, line)
            if match:
                price_str = match.group(1).replace(".", "").replace(",", ".")
                try:
                    price = float(price_str)
                    if price > 0:
                        price_match = price
                        break
                except:
                    pass

        if price_match:
            # Check if it's a special line
            if any(kw in line_lower for kw in ["iva", "impuesto", "tax"]):
                tax = price_match
            elif any(kw in line_lower for kw in ["propina", "tip", "servicio"]):
                tip = price_match
            elif any(kw in line_lower for kw in ["total", "suma", "pago"]):
                total = price_match
            elif any(kw in line_lower for kw in ["subtotal", "neto"]):
                subtotal = price_match
            else:
                # It's likely an item
                # Extract item name (everything before the price)
                name = re.sub(
                    r"\s*\$?\s*\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?\s*$", "", line
                ).strip()
                qty = 1
                prefix_m = re.match(r"^(\d+)\s*[xX\*×]\s*(.+)$", name)
                if prefix_m:
                    qty = int(prefix_m.group(1))
                    name = prefix_m.group(2).strip()
                else:
                    suffix_m = re.match(r"^(.+?)\s+[xX\*×]\s*(\d+)\s*$", name)
                    if suffix_m:
                        name = suffix_m.group(1).strip()
                        qty = int(suffix_m.group(2))
                    else:
                        name = re.sub(
                            r"\s*x?\s*\d+\s*$", "", name
                        ).strip()  # Remove trailing qty-like suffix

                if name and len(name) > 1:
                    line_total = price_match
                    unit_price = line_total / qty if qty > 1 else line_total
                    items.append(
                        {
                            "name": name[:50],  # Limit name length
                            "price": unit_price,
                            "quantity": qty,
                        }
                    )
                    subtotal += line_total

    # If no total found, calculate it
    if total == 0:
        total = subtotal + tax + tip

    return {
        "items": items,
        "subtotal": subtotal,
        "tax": tax,
        "tip": tip,
        "total": total,
    }


def parse_bill_with_openai(image_base64: str) -> dict:
    """Use OpenAI Vision API to parse bill image."""
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)

    prompt = """Analyze this receipt/bill image and extract all items with their prices.
    
    Return a JSON object with this exact structure:
    {
        "items": [
            {"name": "Item name", "price": 10.99, "quantity": 1},
            ...
        ],
        "subtotal": 100.00,
        "tax": 19.00,
        "tip": 0.00,
        "total": 119.00
    }
    
    Rules:
    - Extract ALL items from the receipt
    - For each item set "quantity" to how many units that line represents (e.g. "4 x Pizza" → quantity 4). Use "price" as UNIT price (line total ÷ quantity when quantity > 1).
    - Prices should be numbers (not strings)
    - If tax (IVA, impuesto) is shown separately, include it
    - If tip (propina, service) is shown, include it
    - If you can't determine a value, use 0
    - Calculate totals if not explicitly shown
    - Return ONLY valid JSON, no other text
    """

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                    },
                ],
            }
        ],
        max_tokens=2000,
    )

    result_text = response.choices[0].message.content

    # Clean up response - extract JSON if wrapped in markdown
    if "```json" in result_text:
        result_text = result_text.split("```json")[1].split("```")[0]
    elif "```" in result_text:
        result_text = result_text.split("```")[1].split("```")[0]

    return json.loads(result_text.strip())


@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main frontend page."""
    return FileResponse("static/index.html")


@app.get("/bill/{bill_id}", response_class=HTMLResponse)
async def serve_participant_view(bill_id: str):
    """Serve the participant view page."""
    return FileResponse("static/participant.html")


@app.get("/api/status")
async def get_status():
    """Get API status and configuration."""
    return {
        "status": "ok",
        "ocr_engine": OCR_ENGINE,
        "openai_configured": USE_OPENAI,
        "gemini_configured": USE_GEMINI,
        "storage_mode": database.get_storage_mode(),
        "password_required": bool(APP_PASSWORD),
    }


@app.get("/api/bills")
async def list_all_bills():
    """List all bills from database (for syncing with editor).
    Always fetches fresh from database to ensure all bills are returned."""
    # CRITICAL: Always fetch fresh from database, don't rely on cache
    all_bills_data = database.load_all_bills()

    # Update memory cache with all bills from database
    for bill_id, bill_data in all_bills_data.items():
        try:
            bills_storage[bill_id] = Bill(**bill_data)
        except Exception as e:
            print(f"⚠️ Error parsing bill {bill_id}: {e}")
            continue

    # Return summary of all bills directly from database data (not cache)
    bills_list = []
    for bill_id, bill_data in all_bills_data.items():
        try:
            bill = Bill(**bill_data)
            bills_list.append(
                {
                    "id": bill.id,
                    "title": bill.title,
                    "items_count": len(bill.items),
                    "people_count": len(bill.people),
                    "total": bill.total,
                    "status": bill.status,
                    "created_at": bill.created_at,
                }
            )
        except Exception as e:
            print(f"⚠️ Error processing bill {bill_id} for list: {e}")
            continue

    # Sort by created_at descending (newest first)
    bills_list.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    print(f"📋 Returning {len(bills_list)} bills from database")
    return {"bills": bills_list}


@app.post("/api/auth")
async def authenticate(request: AuthRequest):
    """Authenticate with app password."""
    if not APP_PASSWORD:
        return {"authenticated": True}

    if secrets.compare_digest(request.password, APP_PASSWORD):
        return {"authenticated": True}

    raise HTTPException(status_code=401, detail="Contraseña incorrecta")


@app.get("/api/auth/check")
async def check_auth(password: str = ""):
    """Check if password is correct (via query param for simple check)."""
    if not APP_PASSWORD:
        return {"authenticated": True, "password_required": False}

    if password and secrets.compare_digest(password, APP_PASSWORD):
        return {"authenticated": True, "password_required": True}

    return {"authenticated": False, "password_required": True}


@app.post("/api/create-bill")
async def create_bill(request: CreateBillRequest = CreateBillRequest()):
    """Create a blank bill (no AI scan required)."""
    bill_id = str(uuid.uuid4())[:8]

    title = (request.title or "").strip() or "Boleta"

    bill = Bill(
        id=bill_id,
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
    )

    save_bill(bill)
    return bill


@app.post("/api/scan-bill")
async def scan_bill(file: UploadFile = File(...)):
    """Scan a bill image and extract items."""

    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    try:
        image_bytes = await file.read()

        # Choose OCR method based on available API key
        if OCR_ENGINE == "openai":
            print("Using OpenAI Vision API...")
            image_base64 = encode_image_to_base64(image_bytes)
            parsed_data = parse_bill_with_openai(image_base64)
        elif OCR_ENGINE == "gemini":
            print("Using Google Gemini (FREE)...")
            parsed_data = parse_bill_with_gemini(image_bytes)
        else:
            print("Using Tesseract OCR (free, local)...")
            parsed_data = parse_bill_with_tesseract(image_bytes)

        # Create bill object
        bill_id = str(uuid.uuid4())[:8]

        items = [
            BillItem(
                id=str(uuid.uuid4())[:8],
                name=item["name"],
                price=float(item["price"]),
                quantity=int(item.get("quantity", 1)) or 1,  # Convert to int, default 1
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
            created_at=datetime.now().isoformat(),
        )

        # Store bill (in memory and file)
        save_bill(bill)

        return bill

    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to parse bill data: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")


@app.get("/api/bill/{bill_id}")
async def get_bill(bill_id: str, fresh: bool = True):
    """Get a bill by ID. Always fetches fresh from database by default to ensure data consistency.
    Use ?fresh=false to use cache (not recommended in production)."""
    # Default to fresh=true to always get latest from database
    # This ensures consistency across instances
    bill = fetch_bill(bill_id, force_refresh=fresh)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


def recalculate_bill_totals(bill: Bill) -> Bill:
    """Recalculate all totals for a bill to ensure consistency."""
    # Recalculate subtotal from items
    bill.subtotal = sum(item.price * item.quantity for item in bill.items)

    # Recalculate tip if percentage is set
    if bill.tip_percent > 0:
        bill.tip = bill.subtotal * (bill.tip_percent / 100)

    # Recalculate total
    bill.total = bill.subtotal + bill.tax + bill.tip

    return bill


@app.post("/api/restore-bill")
async def restore_bill(bill: Bill):
    """Restore a bill from client-side storage (for page reload persistence).
    Fetches fresh data from DB first to merge with client changes and prevent data loss."""
    # CRITICAL: Fetch latest from DB first to prevent overwriting concurrent changes
    existing_bill = fetch_bill(bill.id, force_refresh=True)

    # If bill exists in DB, merge important fields to preserve concurrent updates
    if existing_bill:
        # Preserve people and assignments from DB (they might have been updated by participants)
        # But allow client to update items, totals, etc.
        bill.people = existing_bill.people if existing_bill.people else bill.people
        # Assignments always come from DB for matching item ids (including empty list)
        db_by_id = {i.id: i for i in existing_bill.items}
        for client_item in bill.items:
            if client_item.id in db_by_id:
                db_item = db_by_id[client_item.id]
                client_item.claims = dict(db_item.claims)
                client_item.assigned_to = []

    # Recalculate totals to ensure consistency
    bill = recalculate_bill_totals(bill)
    # Ensure new fields have defaults
    if not hasattr(bill, "paid_by") or bill.paid_by is None:
        bill.paid_by = []
    if not hasattr(bill, "locked") or bill.locked is None:
        bill.locked = False
    if not hasattr(bill, "title") or not bill.title:
        bill.title = "Boleta"
    # Store the bill (saves to DB first, then cache)
    save_bill(bill)
    return {"status": "restored", "bill_id": bill.id, "bill": bill}


@app.post("/api/update-title")
async def update_bill_title(request: UpdateBillTitleRequest):
    """Update bill title."""
    bill = fetch_bill(request.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")

    # Keep titles reasonably short
    bill.title = title[:80]
    save_bill(bill)
    return bill


@app.post("/api/update-fintoc-username")
async def update_fintoc_username(request: UpdateFintocUsernameRequest):
    """Update Fintoc username for payment links."""
    bill = fetch_bill(request.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    # Clean the username (remove @ if present, trim whitespace)
    username = request.fintoc_username.strip().lstrip("@")

    bill.fintoc_username = username
    save_bill(bill)
    return bill


@app.post("/api/add-person")
async def add_person(request: AddPersonRequest):
    """Add a person to a bill."""
    bill = fetch_bill(request.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")

    if request.person_name not in bill.people:
        bill.people.append(request.person_name)

    save_bill(bill)
    return bill


@app.post("/api/remove-person")
async def remove_person(request: AddPersonRequest):
    """Remove a person from a bill."""
    bill = fetch_bill(request.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")

    if request.person_name in bill.people:
        bill.people.remove(request.person_name)
        # Also remove from all item claims
        for item in bill.items:
            item.claims.pop(request.person_name, None)
        # Also remove from paid list
        if request.person_name in bill.paid_by:
            bill.paid_by.remove(request.person_name)

    save_bill(bill)
    return bill


@app.post("/api/assign-item")
async def assign_item(request: AssignItemRequest):
    """Assign or unassign a person to a bill item."""
    bill = fetch_bill(request.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")

    # Find item
    item = next((i for i in bill.items if i.id == request.item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    current = float(item.claims.get(request.person_name, 0) or 0)
    if request.units is not None:
        set_item_claim_units(item, request.person_name, request.units)
    elif current > 1e-12:
        set_item_claim_units(item, request.person_name, 0)
    else:
        set_item_claim_units(item, request.person_name, 1.0)

    save_bill(bill)
    return bill


@app.post("/api/split-bill-equally")
async def split_bill_equally(request: SplitBillEquallyRequest):
    """Split each line's units equally among all people on the bill (host action)."""
    bill = fetch_bill(request.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
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

    save_bill(bill)
    return bill


@app.post("/api/update-tip-tax")
async def update_tip_tax(request: UpdateTipTaxRequest):
    """Update tip (as percentage) and tax for a bill."""
    bill = fetch_bill(request.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")

    if request.tip_percent is not None:
        bill.tip_percent = request.tip_percent
        # Calculate tip amount from percentage of subtotal
        bill.tip = bill.subtotal * (request.tip_percent / 100)
    if request.tax is not None:
        bill.tax = request.tax

    # Recalculate total
    bill.total = bill.subtotal + bill.tax + bill.tip

    save_bill(bill)
    return bill


@app.post("/api/add-item")
async def add_item(request: AddItemRequest):
    """Manually add an item to a bill."""
    bill = fetch_bill(request.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")

    new_item = BillItem(
        id=str(uuid.uuid4())[:8],
        name=request.name,
        price=request.price,
        quantity=request.quantity,
        claims={},
    )

    bill.items.append(new_item)
    bill.subtotal += new_item.price * new_item.quantity
    # Recalculate tip from percentage
    if bill.tip_percent > 0:
        bill.tip = bill.subtotal * (bill.tip_percent / 100)
    bill.total = bill.subtotal + bill.tax + bill.tip

    save_bill(bill)
    return bill


@app.delete("/api/item/{bill_id}/{item_id}")
async def delete_item(bill_id: str, item_id: str):
    """Delete an item from a bill."""
    bill = fetch_bill(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    if bill.locked:
        raise HTTPException(status_code=403, detail="Bill is locked")

    item = next((i for i in bill.items if i.id == item_id), None)

    if item:
        bill.subtotal -= item.price * item.quantity
        bill.items = [i for i in bill.items if i.id != item_id]
        # Recalculate tip from percentage
        if bill.tip_percent > 0:
            bill.tip = bill.subtotal * (bill.tip_percent / 100)
        bill.total = bill.subtotal + bill.tax + bill.tip

    save_bill(bill)
    return bill


@app.post("/api/lock-bill")
async def lock_bill(request: LockBillRequest):
    """Lock or unlock a bill."""
    bill = fetch_bill(request.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    bill.locked = request.locked

    save_bill(bill)
    return bill


@app.post("/api/mark-paid")
async def mark_paid(request: MarkPaidRequest):
    """Mark a person as paid or unpaid."""
    bill = fetch_bill(request.bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    if request.paid:
        if request.person_name not in bill.paid_by:
            bill.paid_by.append(request.person_name)
    else:
        if request.person_name in bill.paid_by:
            bill.paid_by.remove(request.person_name)

    save_bill(bill)
    return bill


# ============ PARTICIPANT VIEW ENDPOINTS ============


@app.get("/api/bill/{bill_id}/participant")
async def get_bill_for_participant(bill_id: str):
    """Get bill data for participant view (read-only overview).
    Always fetches fresh from database to ensure it works across all instances."""
    # CRITICAL: Always fetch fresh from DB for participant view
    # This ensures it works even if the bill isn't in this instance's cache
    bill = fetch_bill(bill_id, force_refresh=True)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    # Calculate splits for each person
    person_totals = {person: 0.0 for person in bill.people}

    for item in bill.items:
        for person, units in item.claims.items():
            if person in person_totals and units > 1e-12:
                person_totals[person] += person_line_dollar_share(item, person)

    # Add proportional tip and tax
    if bill.subtotal > 0:
        for person in person_totals:
            proportion = person_totals[person] / bill.subtotal
            person_totals[person] += (bill.tip * proportion) + (bill.tax * proportion)

    # Generate payment links (only if fintoc_username is set)
    payment_links = {}
    fintoc_user = bill.fintoc_username or FINTOC_USERNAME
    if fintoc_user:
        for person, total in person_totals.items():
            rounded = round(total)
            payment_links[person] = f"https://fintoc.me/{fintoc_user}/{rounded}"

    return {
        "bill": bill,
        "person_totals": person_totals,
        "payment_links": payment_links,
    }


@app.post("/api/bill/{bill_id}/join")
async def join_bill(bill_id: str, request: JoinBillRequest):
    """Join a bill as a new participant. Fetches fresh data from DB to prevent overwriting concurrent changes."""
    # CRITICAL: Always fetch fresh from DB to prevent overwriting concurrent updates
    bill = fetch_bill(bill_id, force_refresh=True)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    # Don't allow joining locked or closed bills
    if bill.locked:
        raise HTTPException(status_code=403, detail="La cuenta está bloqueada")
    if bill.status == "closed":
        raise HTTPException(status_code=403, detail="La cuenta está cerrada")

    person_name = request.person_name.strip()
    if not person_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    if person_name in bill.people:
        raise HTTPException(status_code=400, detail="Name already exists")

    bill.people.append(person_name)
    save_bill(bill)

    return {"status": "joined", "person_name": person_name, "bill": bill}


@app.post("/api/bill/{bill_id}/self-assign")
async def self_assign_item(bill_id: str, request: SelfAssignRequest):
    """Participant assigns themselves to an item. Fetches fresh data from DB to prevent overwriting concurrent changes."""
    # CRITICAL: Always fetch fresh from DB to prevent overwriting concurrent updates
    bill = fetch_bill(bill_id, force_refresh=True)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    # Don't allow changes on locked or closed bills
    if bill.locked:
        raise HTTPException(status_code=403, detail="La cuenta está bloqueada")
    if bill.status == "closed":
        raise HTTPException(status_code=403, detail="La cuenta está cerrada")

    # Find the item
    item = next((i for i in bill.items if i.id == request.item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Verify person exists in bill
    if request.person_name not in bill.people:
        raise HTTPException(status_code=400, detail="Person not in bill")

    if request.assigned:
        set_item_claim_units(item, request.person_name, request.units)
    else:
        set_item_claim_units(item, request.person_name, 0)

    # Save with force_refresh to ensure we have latest data
    save_bill(bill)

    return {"status": "updated", "bill": bill}


@app.post("/api/bill/{bill_id}/status")
async def set_bill_status(bill_id: str, request: SetBillStatusRequest):
    """Set bill status (draft, ready, closed)."""
    if request.status not in ["draft", "ready", "closed"]:
        raise HTTPException(status_code=400, detail="Invalid status")

    bill = fetch_bill(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    bill.status = request.status

    # Sync locked state with status
    if request.status in ["ready", "closed"]:
        bill.locked = True
    elif request.status == "draft":
        # IMPORTANT: allow going back to draft to unlock the bill
        bill.locked = False

    save_bill(bill)

    return {"status": "updated", "bill": bill}


@app.post("/api/refresh-bill/{bill_id}")
async def refresh_bill_cache(bill_id: str):
    """Force refresh a bill from database (bypasses cache). Useful when seeing stale data."""
    bill = refresh_bill_from_db(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")
    return {"status": "refreshed", "bill": bill}


@app.post("/api/refresh-all-bills")
async def refresh_all_bills_cache():
    """Force refresh all bills from database (bypasses cache). Useful when seeing stale data."""
    # Reload all bills from database
    load_bills_from_storage()
    return {
        "status": "refreshed",
        "bills_count": len(bills_storage),
        "message": "All bills refreshed from database",
    }


@app.get("/api/calculate-splits/{bill_id}")
async def calculate_splits(bill_id: str):
    """Calculate how much each person owes."""
    bill = fetch_bill(bill_id)
    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    # Calculate per-person totals
    person_totals = {person: 0.0 for person in bill.people}

    for item in bill.items:
        for person, units in item.claims.items():
            if units > 1e-12 and person in person_totals:
                person_totals[person] += person_line_dollar_share(item, person)

    # Calculate proportional tax and tip
    items_subtotal = sum(item.price * item.quantity for item in bill.items)

    if items_subtotal > 0:
        for person in person_totals:
            person_share = person_totals[person] / items_subtotal
            person_totals[person] += (bill.tax + bill.tip) * person_share

    # Round to 2 decimal places
    person_totals = {k: round(v, 2) for k, v in person_totals.items()}

    # Generate Fintoc payment links (only if fintoc_username is set)
    payment_links = {}
    fintoc_user = bill.fintoc_username or FINTOC_USERNAME
    if fintoc_user:
        for person, total in person_totals.items():
            if total > 0:
                # Round to integer for the link (Fintoc uses integer amounts)
                amount = int(round(total))
                payment_links[person] = f"https://fintoc.me/{fintoc_user}/{amount}"

    return {
        "bill_id": bill_id,
        "person_totals": person_totals,
        "payment_links": payment_links,
        "bill_total": bill.total,
        "assigned_total": sum(person_totals.values()),
    }


# Live reload WebSocket connections
live_reload_clients: list[WebSocket] = []


@app.websocket("/ws/live-reload")
async def live_reload_websocket(websocket: WebSocket):
    """WebSocket endpoint for live reload."""
    await websocket.accept()
    live_reload_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except:
        pass
    finally:
        if websocket in live_reload_clients:
            live_reload_clients.remove(websocket)


async def notify_reload():
    """Notify all connected clients to reload."""
    for client in live_reload_clients[:]:
        try:
            await client.send_text("reload")
        except:
            live_reload_clients.remove(client)


# Mount static files
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# File watcher for live reload
async def watch_static_files():
    """Watch static files and notify clients on changes."""
    try:
        from watchfiles import awatch

        print("👀 Watching static files for changes...")
        async for changes in awatch("static"):
            print(f"🔄 Files changed: {changes}")
            await notify_reload()
    except ImportError:
        print("⚠️ watchfiles not installed, live reload disabled for static files")
    except Exception as e:
        print(f"File watcher error: {e}")


@app.on_event("startup")
async def startup_event():
    """Start file watcher on app startup."""
    asyncio.create_task(watch_static_files())


if __name__ == "__main__":
    import uvicorn

    engine_names = {
        "openai": "OpenAI Vision",
        "gemini": "Google Gemini (FREE)",
        "tesseract": "Tesseract (FREE)",
    }
    print(f"OCR Engine: {engine_names.get(OCR_ENGINE, OCR_ENGINE)}")
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
