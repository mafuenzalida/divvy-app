"""Minor-unit money and unified split totals."""

from __future__ import annotations

import math

from app.domain.models import Bill
from app.services.splits import person_line_dollar_share

SCALE = 100


def to_minor(amount: float) -> int:
    return int(round(float(amount) * SCALE))


def from_minor(minor: int) -> float:
    return round(minor / SCALE, 2)


def compute_items_subtotal_minor(bill: Bill) -> int:
    total = 0
    for item in bill.items:
        total += to_minor(item.price * item.quantity)
    return total


def compute_person_item_subtotals_minor(bill: Bill) -> dict[str, int]:
    out: dict[str, int] = {p: 0 for p in bill.people}
    for item in bill.items:
        for person, units in item.claims.items():
            if person in out and units > 1e-12:
                share = person_line_dollar_share(item, person)
                out[person] += to_minor(share)
    return out


def _distribute_largest_remainder(total_units: int, weights: dict[str, float]) -> dict[str, int]:
    """Split total_units across keys proportional to weights (>=0). Deterministic."""
    if total_units == 0:
        return {k: 0 for k in weights}
    sw = sum(max(0.0, w) for w in weights.values())
    if sw <= 0:
        keys = sorted(weights.keys())
        if not keys:
            return {}
        base, rem = divmod(total_units, len(keys))
        return {k: base + (1 if i < rem else 0) for i, k in enumerate(keys)}

    floors: dict[str, int] = {}
    fracs: list[tuple[float, str]] = []
    for k in sorted(weights.keys()):
        w = max(0.0, float(weights[k]))
        exact = total_units * (w / sw)
        fl = int(math.floor(exact + 1e-12))
        floors[k] = fl
        fracs.append((exact - fl, k))
    assigned = sum(floors.values())
    leftover = total_units - assigned
    fracs.sort(key=lambda x: (-x[0], x[1]))
    i = 0
    while leftover > 0:
        _, k = fracs[i % len(fracs)]
        floors[k] += 1
        leftover -= 1
        i += 1
    return floors


def compute_person_totals_minor(bill: Bill) -> dict[str, int]:
    """
    Per-person totals in minor units: assigned item shares plus proportional tax+tip.
    Uses bill.subtotal (stored) as denominator for tax/tip proportion, matching prior API behavior.
    """
    item_sub = compute_person_item_subtotals_minor(bill)
    tax_tip_minor = to_minor(bill.tax) + to_minor(bill.tip)
    base_minor = to_minor(bill.subtotal)

    if tax_tip_minor == 0 or base_minor <= 0:
        return item_sub

    extras = _distribute_largest_remainder(tax_tip_minor, {p: float(item_sub.get(p, 0)) for p in bill.people})
    return {p: item_sub.get(p, 0) + extras.get(p, 0) for p in bill.people}


def fintoc_link_amount_minor(person_minor: int) -> int:
    return max(0, int(round(person_minor)))
