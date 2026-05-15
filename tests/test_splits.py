"""Split math tests (line shares + minor-unit totals)."""

from app.domain.models import Bill, BillItem
from app.services.money import compute_person_totals_minor, from_minor
from app.services.splits import person_line_dollar_share, set_item_claim_units


def _bill(**kwargs) -> Bill:
    defaults = dict(
        id="testid",
        title="T",
        items=[],
        subtotal=0.0,
        tax=0.0,
        tip=0.0,
        tip_percent=0.0,
        total=0.0,
        people=["A", "B"],
        paid_by=[],
        locked=False,
        status="draft",
        created_at="2020-01-01T00:00:00",
        host_token="h",
        participant_token="p",
        owner_user_id=None,
        version=0,
    )
    defaults.update(kwargs)
    return Bill(**defaults)


def test_qty_one_two_people_half_each():
    item = BillItem(id="i1", name="x", price=100.0, quantity=1, claims={})
    set_item_claim_units(item, "A", 0.5)
    set_item_claim_units(item, "B", 0.5)
    assert abs(person_line_dollar_share(item, "A") - 50.0) < 1e-6


def test_qty_one_weights_gt_one_split_proportionally():
    item = BillItem(id="i1", name="x", price=100.0, quantity=1, claims={})
    set_item_claim_units(item, "A", 1.0)
    set_item_claim_units(item, "B", 1.0)
    sa = person_line_dollar_share(item, "A")
    sb = person_line_dollar_share(item, "B")
    assert abs(sa - 50.0) < 1e-6 and abs(sb - 50.0) < 1e-6


def test_qty_two_each_one_unit():
    item = BillItem(id="i1", name="x", price=50.0, quantity=2, claims={})
    set_item_claim_units(item, "A", 1.0)
    set_item_claim_units(item, "B", 1.0)
    assert abs(person_line_dollar_share(item, "A") - 50.0) < 1e-6


def test_tax_tip_proportional_minor():
    items = [
        BillItem(id="i1", name="a", price=100.0, quantity=1, claims={"A": 1.0}),
        BillItem(id="i2", name="b", price=100.0, quantity=1, claims={"B": 1.0}),
    ]
    bill = _bill(
        items=items,
        subtotal=200.0,
        tax=20.0,
        tip=10.0,
        total=230.0,
    )
    m = compute_person_totals_minor(bill)
    total_minor = m["A"] + m["B"]
    assert abs(total_minor - 23000) < 5
