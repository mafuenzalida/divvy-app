# Database migrations (Divvy)

## Turso / SQLite

On first connection after upgrading, the app runs `CREATE TABLE IF NOT EXISTS` and `ALTER TABLE` for missing columns on the `bills` table:

- `host_token`, `participant_token`, `owner_user_id`, `version`
- Separate tables: `users`, `sessions`, `magic_links`

Existing rows in `bills.data` JSON are normalized on read: missing `host_token` / `participant_token` are generated once and written back.

## Breaking change: bill URLs

Older links used short numeric/alpha bill IDs and paths like `/bill/{bill_id}` for participants. New links:

- Participant: `/b/{participant_token}`
- Host (edit): `/edit/{host_token}` (sets an HttpOnly cookie for host API access)

Public listing `GET /api/bills` was removed; signed-in users use `GET /api/me/bills` for bills they have claimed.

The host web UI lives at **`/app`** (upload and edit). **`/`** is a small landing page; **`/login`** is the magic-link sign-in page.

## Local JSON file

The same bill JSON fields are added when bills are loaded or saved to `data/bills.json`.

## One-off: assign bill owner (`owner_user_id`)

`GET /api/me/bills` only returns rows whose bill JSON has `owner_user_id` equal to the signed-in user. Older bills may have no owner.

Run once per environment (Turso or local JSON), after `.env` is loaded:

```bash
MIGRATE_OWNER_EMAIL=mfuenzalida@live.com python scripts/migrate_bills_owner.py
```

The script creates the user if missing, sets `is_admin = 1` for that email, and sets `owner_user_id` on every bill that does not already have one. Tokens in each bill are unchanged.

For `/api/admin/bills`, set `ADMIN_EMAILS` to a comma-separated list that includes that same email in production.
