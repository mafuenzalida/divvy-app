"""Line-item claim math (float dollars at item level)."""

from app.domain.models import BillItem


def item_other_claims_sum(item: BillItem, person_name: str) -> float:
    return sum(u for p, u in item.claims.items() if p != person_name)


def item_claim_weight_sum(item: BillItem) -> float:
    return sum(float(w) for w in item.claims.values() if w > 1e-12)


def set_item_claim_units(item: BillItem, person_name: str, units: float) -> None:
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
