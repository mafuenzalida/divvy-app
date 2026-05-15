"""Merge DB bill into client restore payload so participant updates are not lost."""

from app.domain.models import Bill


def merge_restore_bill_from_existing(client: Bill, existing: Bill) -> None:
    """
    When the host POSTs /api/restore-bill, the client payload may be stale.
    DB wins for: people list, item claims, paid_by (participants update these server-side).
    """
    if existing.people:
        client.people = list(existing.people)
    db_by_id = {i.id: i for i in existing.items}
    for client_item in client.items:
        if client_item.id in db_by_id:
            db_item = db_by_id[client_item.id]
            client_item.claims = dict(db_item.claims)
            client_item.assigned_to = []
    client.paid_by = list(existing.paid_by or [])
