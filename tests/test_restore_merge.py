"""Regression: restore merge must keep DB paid_by when client is stale."""

from app.domain.models import Bill, BillItem
from app.services.restore_merge import merge_restore_bill_from_existing


def _base_bill(**kwargs):
    d = dict(
        id="bid1",
        title="T",
        items=[
            BillItem(id="i1", name="x", price=10.0, quantity=1, claims={"A": 1.0}),
        ],
        subtotal=10.0,
        tax=0.0,
        tip=0.0,
        tip_percent=0.0,
        total=10.0,
        people=["A", "B"],
        paid_by=[],
        locked=False,
        status="draft",
        created_at="2020-01-01",
        host_token="h",
        participant_token="p",
        owner_user_id=None,
        version=1,
    )
    d.update(kwargs)
    return Bill(**d)


def test_merge_preserves_paid_by_from_db_when_client_empty():
    client = _base_bill(paid_by=[], version=0)
    existing = _base_bill(paid_by=["A"], version=3)
    merge_restore_bill_from_existing(client, existing)
    assert client.paid_by == ["A"]


def test_merge_claims_from_db():
    client = _base_bill(
        items=[BillItem(id="i1", name="x", price=10.0, quantity=1, claims={})],
        paid_by=[],
    )
    existing = _base_bill(
        items=[BillItem(id="i1", name="x", price=10.0, quantity=1, claims={"B": 1.0})],
        paid_by=["B"],
    )
    merge_restore_bill_from_existing(client, existing)
    assert client.items[0].claims == {"B": 1.0}
    assert client.paid_by == ["B"]
