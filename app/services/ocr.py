"""Receipt OCR backends."""

from __future__ import annotations

import base64
import io
import json
import logging
import re

from PIL import Image

from app.core.config import get_settings

LOG = logging.getLogger("divvy")


def encode_image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def parse_bill_with_gemini(image_bytes: bytes) -> dict:
    import google.generativeai as genai

    s = get_settings()
    genai.configure(api_key=s.gemini_api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    image = Image.open(io.BytesIO(image_bytes))
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
        if not response.candidates:
            feedback = getattr(response, "prompt_feedback", None)
            raise ValueError(f"Gemini blocked the request: {feedback}")
        result_text = response.text
    except ValueError as e:
        if "blocked" in str(e).lower() or "empty" in str(e).lower():
            simple_prompt = 'List all items from this receipt as JSON: {"items": [{"name": "...", "price": 0, "quantity": 1}], "total": 0}. Use quantity>1 when a line shows multiples; price = unit price.'
            response = model.generate_content([simple_prompt, image])
            if not response.candidates:
                raise ValueError(
                    "Gemini could not process this image. Try a clearer photo."
                ) from e
            result_text = response.text
        else:
            raise
    if "```json" in result_text:
        result_text = result_text.split("```json")[1].split("```")[0]
    elif "```" in result_text:
        result_text = result_text.split("```")[1].split("```")[0]
    parsed = json.loads(result_text.strip())
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
    try:
        import pytesseract
    except ImportError as e:
        raise RuntimeError(
            "Tesseract OCR is not available: install pytesseract and system tesseract."
        ) from e
    image = Image.open(io.BytesIO(image_bytes))
    if image.mode != "L":
        image = image.convert("L")
    text = pytesseract.image_to_string(image, lang="spa+eng")
    LOG.debug("ocr_tesseract_chars=%s", len(text))
    items = []
    lines = text.strip().split("\n")
    price_patterns = [
        r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)\s*$",
        r"\$\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?)",
        r"(\d+(?:[.,]\d+)?)\s*(?:CLP|clp)?$",
    ]
    subtotal = 0.0
    tax = 0.0
    tip = 0.0
    total = 0.0
    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue
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
        line_lower = line.lower()
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
                except ValueError:
                    pass
        if price_match:
            if any(kw in line_lower for kw in ["iva", "impuesto", "tax"]):
                tax = price_match
            elif any(kw in line_lower for kw in ["propina", "tip", "servicio"]):
                tip = price_match
            elif any(kw in line_lower for kw in ["total", "suma", "pago"]):
                total = price_match
            elif any(kw in line_lower for kw in ["subtotal", "neto"]):
                subtotal = price_match
            else:
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
                        name = re.sub(r"\s*x?\s*\d+\s*$", "", name).strip()
                if name and len(name) > 1:
                    line_total = price_match
                    unit_price = line_total / qty if qty > 1 else line_total
                    items.append(
                        {
                            "name": name[:50],
                            "price": unit_price,
                            "quantity": qty,
                        }
                    )
                    subtotal += line_total
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
    from openai import OpenAI

    s = get_settings()
    client = OpenAI(api_key=s.openai_api_key)
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
    if "```json" in result_text:
        result_text = result_text.split("```json")[1].split("```")[0]
    elif "```" in result_text:
        result_text = result_text.split("```")[1].split("```")[0]
    return json.loads(result_text.strip())
