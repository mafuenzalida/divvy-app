"""Turn raw OCR JSON into line items whose prices sum to the bill total."""

from __future__ import annotations

import re
from typing import Any

_SUMMARY_NAME = re.compile(
    r"""
    ^
    (
        sub\s*total
        | total(\s+(a\s+pagar|general|boleta|cuenta))?
        | iva(\s*\d+\s*%)?
        | impuesto(s)?
        | tax
        | propina(\s+sugerida)?
        | tip
        | servicio(\s*de\s+mesa)?(\s*\d+\s*%)?
        | neto
        | pag[oa](\s+total)?
        | vuelto
        | cambio
        | descuento
        | amount\s*due
        | balance
    )
    \s*[:.\-]*\s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
_QTY_PREFIX = re.compile(r"^(\d+)\s*[xX\*×]\s*(.+)$")
_QTY_SUFFIX = re.compile(r"^(.+?)\s+[xX\*×]\s*(\d+)\s*$")
_MAX_AJUSTE_RATIO = 0.25


def _to_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return 0.0
    raw = value.strip().replace("$", "").replace(" ", "").replace("\u00a0", "")
    if not raw:
        return 0.0
    if raw.count(".") > 1 and "," not in raw:
        raw = raw.replace(".", "")
    elif raw.count(",") > 1 and "." not in raw:
        raw = raw.replace(",", "")
    elif "," in raw and raw.rfind(",") > raw.rfind("."):
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _close(a: float, b: float, rel: float = 0.03, abs_tol: float = 2.0) -> bool:
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b), 1.0))


def _qty_from_name(name: str) -> tuple[str, int | None]:
    text = name.strip()
    match = _QTY_PREFIX.match(text)
    if match:
        qty = int(match.group(1))
        cleaned = match.group(2).strip()
        return cleaned, qty if qty > 1 else None
    match = _QTY_SUFFIX.match(text)
    if match:
        qty = int(match.group(2))
        cleaned = match.group(1).strip()
        return cleaned, qty if qty > 1 else None
    return text, None


def _item_qty(item: dict) -> int:
    return int(item.get("quantity", 1) or 1)


def _item_line(item: dict) -> float:
    return float(item.get("price", 0) or 0) * _item_qty(item)


def _line_sum(items: list[dict]) -> float:
    return sum(_item_line(i) for i in items)


def _price_sum(items: list[dict]) -> float:
    return sum(float(i.get("price", 0) or 0) for i in items)


def _clean_items(raw_items: list[Any]) -> list[dict]:
    cleaned: list[dict] = []
    for raw in raw_items or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name or _SUMMARY_NAME.match(name):
            continue
        name, name_qty = _qty_from_name(name)
        qty = int(_to_float(raw.get("quantity", 1)) or 1)
        if qty < 1:
            qty = 1
        if qty <= 1 and name_qty:
            qty = name_qty
        line_total = raw.get("line_total")
        if line_total is not None and _to_float(line_total) > 0:
            price = _to_float(line_total) / qty
        else:
            price = _to_float(raw.get("price", 0))
        if price <= 0 or not name:
            continue
        cleaned.append({"name": name[:80], "price": price, "quantity": qty})
    return cleaned


def _unscale_all_if_prices_match(items: list[dict], reference: float) -> None:
    if reference <= 0 or not items:
        return
    if not any(_item_qty(i) > 1 for i in items):
        return
    by_line = _line_sum(items)
    by_price = _price_sum(items)
    if _close(by_line, reference):
        return
    if _close(by_price, reference) and abs(by_line - reference) > abs(by_price - reference):
        for item in items:
            qty = _item_qty(item)
            if qty > 1:
                item["price"] = float(item["price"]) / qty


def _unscale_mixed_line_totals(items: list[dict], reference: float) -> None:
    """Divide only the qty>1 rows that move the sum closer to the receipt."""
    if reference <= 0 or not items:
        return
    if _close(_line_sum(items), reference):
        return
    improved = True
    while improved:
        improved = False
        current_dist = abs(_line_sum(items) - reference)
        best_i: int | None = None
        best_dist = current_dist
        for i, item in enumerate(items):
            qty = _item_qty(item)
            if qty <= 1:
                continue
            original = float(item["price"])
            item["price"] = original / qty
            dist = abs(_line_sum(items) - reference)
            item["price"] = original
            if dist + 1e-6 < best_dist:
                best_dist = dist
                best_i = i
        if best_i is not None:
            qty = _item_qty(items[best_i])
            items[best_i]["price"] = float(items[best_i]["price"]) / qty
            improved = True
            if _close(_line_sum(items), reference):
                return


def _maybe_unscale_line_totals(items: list[dict], reference: float) -> None:
    _unscale_all_if_prices_match(items, reference)
    _unscale_mixed_line_totals(items, reference)


def _maybe_fix_thousands(items: list[dict], reference: float) -> None:
    """JSON 12.500 becomes 12.5; CLP receipts need 12500."""
    if reference < 1000 or not items:
        return
    current = _line_sum(items)
    if current <= 0:
        return
    scaled = current * 1000.0
    if reference / current > 50 and _close(scaled, reference, rel=0.05):
        for item in items:
            item["price"] = float(item["price"]) * 1000.0


def _drop_duplicate_total_rows(items: list[dict], ocr_total: float) -> None:
    """Drop a copied TOTAL line when removing it gets closer to the receipt total."""
    if ocr_total <= 0 or len(items) < 2:
        return
    while len(items) >= 2:
        current = _line_sum(items)
        current_dist = abs(current - ocr_total)
        if current <= ocr_total + 1:
            return
        best_i: int | None = None
        best_dist = current_dist
        for i in range(len(items) - 1, -1, -1):
            line = _item_line(items[i])
            if not _close(line, ocr_total):
                continue
            trial = current - line
            if trial <= 0:
                continue
            dist = abs(trial - ocr_total)
            if dist + 1e-6 < best_dist:
                best_dist = dist
                best_i = i
                break
        if best_i is None:
            return
        items.pop(best_i)


def _pick_tax_tip(
    subtotal: float, ocr_tax: float, ocr_tip: float, ocr_total: float
) -> tuple[float, float]:
    if ocr_total <= 0:
        return max(0.0, ocr_tax), max(0.0, ocr_tip)
    candidates = [
        (0.0, 0.0),
        (max(0.0, ocr_tax), 0.0),
        (0.0, max(0.0, ocr_tip)),
        (max(0.0, ocr_tax), max(0.0, ocr_tip)),
    ]
    return min(candidates, key=lambda pair: abs(subtotal + pair[0] + pair[1] - ocr_total))


def _maybe_add_remainder(items: list[dict], target_total: float, tax: float, tip: float) -> None:
    if target_total <= 0:
        return
    current = _line_sum(items) + tax + tip
    remainder = round(target_total - current, 2)
    if remainder < 1:
        return
    if remainder > target_total * _MAX_AJUSTE_RATIO:
        return
    items.append(
        {
            "name": "Ajuste (faltante OCR)",
            "price": remainder,
            "quantity": 1,
        }
    )


def normalize_parsed_receipt(parsed: dict) -> dict:
    """
    Drop summary rows, fix unit vs line totals, and set
    subtotal = Σ(price × quantity), total = subtotal + tax + tip.
    """
    ocr_subtotal = _to_float(parsed.get("subtotal", 0))
    ocr_tax = _to_float(parsed.get("tax", 0))
    ocr_tip = _to_float(parsed.get("tip", 0))
    ocr_total = _to_float(parsed.get("total", 0))
    items = _clean_items(parsed.get("items") or [])

    reference = ocr_subtotal if ocr_subtotal > 0 else max(0.0, ocr_total - ocr_tax - ocr_tip)
    _maybe_unscale_line_totals(items, reference)
    _maybe_unscale_line_totals(items, ocr_total)
    _maybe_fix_thousands(items, ocr_subtotal if ocr_subtotal > 0 else ocr_total)
    _drop_duplicate_total_rows(items, ocr_total)

    subtotal = _line_sum(items)
    tax, tip = _pick_tax_tip(subtotal, ocr_tax, ocr_tip, ocr_total)
    _maybe_add_remainder(items, ocr_total, tax, tip)
    subtotal = _line_sum(items)

    return {
        "items": items,
        "subtotal": subtotal,
        "tax": tax,
        "tip": tip,
        "total": subtotal + tax + tip,
    }
