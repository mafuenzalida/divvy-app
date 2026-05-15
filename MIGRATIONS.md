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

## Local JSON file

The same bill JSON fields are added when bills are loaded or saved to `data/bills.json`.
