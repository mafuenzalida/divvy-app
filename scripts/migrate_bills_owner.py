#!/usr/bin/env python3
"""
One-off: create/promote admin user and set owner_user_id on all bills without one.

  MIGRATE_OWNER_EMAIL=mfuenzalida@live.com python scripts/migrate_bills_owner.py

Requires .env with same DB vars as the app (Turso or local JSON).
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db as database  # noqa: E402


def main() -> None:
    email = os.environ.get("MIGRATE_OWNER_EMAIL", "mfuenzalida@live.com").strip().lower()
    if "@" not in email:
        print("Invalid MIGRATE_OWNER_EMAIL", file=sys.stderr)
        sys.exit(1)

    user = database.get_user_by_email(email)
    if not user:
        user = database.create_user(email, is_admin=True)
        print(f"Created user {email!r} id={user['id']}")
    else:
        database.set_user_admin(email, True)
        user = database.get_user_by_email(email)
        print(f"Promoted {email!r} to admin id={user['id']}")

    uid = user["id"]
    bills = database.load_all_bills()
    attached = 0
    for bill_id, data in bills.items():
        if data.get("owner_user_id"):
            continue
        d = dict(data)
        d["owner_user_id"] = uid
        database.save_bill(bill_id, d)
        attached += 1

    print(
        f"Attached owner_user_id to {attached} bill(s); "
        f"{len(bills) - attached} already had an owner."
    )
    print("Set ADMIN_EMAILS in production to this email for /api/admin/* access.")


if __name__ == "__main__":
    main()
