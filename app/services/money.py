"""Minor-unit money and unified split totals."""

from __future__ import annotations

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


def _person_tax_tip_extras_minor(
    tax_tip_minor: int, item_sub: dict[str, int], base_minor: int, people: list[str]
) -> dict[str, int]:
    """Per-person tax+tip in minor units; unclaimed bill share keeps its tax/tip unassigned."""
    if tax_tip_minor == 0 or base_minor <= 0:
        return {p: 0 for p in people}
    extras: dict[str, int] = {}
    for p in people:
        share = item_sub.get(p, 0)
        if share <= 0:
            extras[p] = 0
        else:
            extras[p] = int(round(tax_tip_minor * share / base_minor))
    return extras


def compute_person_totals_minor(bill: Bill) -> dict[str, int]:
    """
    Per-person totals in minor units: assigned item shares plus proportional tax+tip.
    Tax/tip share is (person item subtotal / bill subtotal), so unclaimed items do not
    inflate anyone's tip or tax.
    """
    item_sub = compute_person_item_subtotals_minor(bill)
    tax_tip_minor = to_minor(bill.tax) + to_minor(bill.tip)
    base_minor = compute_items_subtotal_minor(bill)

    if tax_tip_minor == 0 or base_minor <= 0:
        return item_sub

    extras = _person_tax_tip_extras_minor(tax_tip_minor, item_sub, base_minor, bill.people)
    return {p: item_sub.get(p, 0) + extras.get(p, 0) for p in bill.people}


def fintoc_link_amount_minor(person_minor: int) -> int:
    """Fintoc CLP links use whole pesos, not cent-style minor units."""
    return max(0, int(round(person_minor / SCALE)))
