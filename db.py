"""
Database adapter for Divvy
- Turso (libsql) when TURSO_DATABASE_URL + TURSO_AUTH_TOKEN are set
- Falls back to local JSON files
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")
USE_TURSO = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)

BILLS_FILE = "data/bills.json"
AUTH_FILE = "data/auth_store.json"

_turso_client = None


def _auth_store_path() -> str:
    return AUTH_FILE


def _load_auth_file() -> dict[str, Any]:
    path = _auth_store_path()
    if not os.path.exists(path):
        return {"users": {}, "sessions": {}, "magic_links": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("users", {})
            data.setdefault("sessions", {})
            data.setdefault("magic_links", {})
            return data
    except Exception:
        return {"users": {}, "sessions": {}, "magic_links": {}}


def _save_auth_file(store: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(_auth_store_path()) or ".", exist_ok=True)
    with open(_auth_store_path(), "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def get_storage_mode() -> str:
    return "turso" if USE_TURSO else "local_file"


def _get_turso_client():
    global _turso_client
    if _turso_client is None and USE_TURSO:
        try:
            import libsql_experimental as libsql

            if not TURSO_DATABASE_URL or not TURSO_AUTH_TOKEN:
                return None
            _turso_client = libsql.connect(
                TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN
            )
            _migrate_turso(_turso_client)
            _turso_client.commit()
        except ImportError:
            return None
        except Exception:
            import traceback

            traceback.print_exc()
            return None
    return _turso_client


def _migrate_turso(client) -> None:
    client.execute(
        """
        CREATE TABLE IF NOT EXISTS bills (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            host_token TEXT,
            participant_token TEXT,
            owner_user_id TEXT,
            version INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    client.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    client.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """
    )
    client.execute(
        """
        CREATE TABLE IF NOT EXISTS magic_links (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT
        )
        """
    )
    # Add missing columns on old DBs
    cur = client.execute("PRAGMA table_info(bills)")
    cols = {row[1] for row in cur.fetchall()}
    if "host_token" not in cols:
        client.execute("ALTER TABLE bills ADD COLUMN host_token TEXT")
    if "participant_token" not in cols:
        client.execute("ALTER TABLE bills ADD COLUMN participant_token TEXT")
    if "owner_user_id" not in cols:
        client.execute("ALTER TABLE bills ADD COLUMN owner_user_id TEXT")
    if "version" not in cols:
        client.execute("ALTER TABLE bills ADD COLUMN version INTEGER NOT NULL DEFAULT 0")
    client.execute(
        "CREATE INDEX IF NOT EXISTS idx_bills_host ON bills(host_token)"
    )
    client.execute(
        "CREATE INDEX IF NOT EXISTS idx_bills_participant ON bills(participant_token)"
    )
    client.execute(
        "CREATE INDEX IF NOT EXISTS idx_bills_owner ON bills(owner_user_id)"
    )


def normalize_bill_row_data(bill_data: dict) -> tuple[dict, bool]:
    """Ensure security fields exist. Returns (dict, changed)."""
    import secrets as sec

    d = dict(bill_data)
    changed = False
    if not d.get("host_token"):
        d["host_token"] = sec.token_urlsafe(32)
        changed = True
    if not d.get("participant_token"):
        d["participant_token"] = sec.token_urlsafe(16)
        changed = True
    if d.get("version") is None:
        d["version"] = 0
        changed = True
    if "owner_user_id" not in d:
        d["owner_user_id"] = None
        changed = True
    return d, changed


def _merge_bill_row(bill_data: dict, row: tuple) -> dict:
    """Row: id, data, host_token, participant_token, owner_user_id, version."""
    d = dict(bill_data)
    if len(row) > 2 and row[2]:
        d["host_token"] = row[2]
    if len(row) > 3 and row[3]:
        d["participant_token"] = row[3]
    if len(row) > 4 and row[4] is not None:
        d["owner_user_id"] = row[4]
    if len(row) > 5 and row[5] is not None:
        d["version"] = int(row[5])
    return d


def _merge_bill_data_row(bill_data: dict, r: tuple) -> dict:
    """Row from SELECT data, host_token, participant_token, owner_user_id, version."""
    d = dict(bill_data)
    if len(r) > 1 and r[1]:
        d["host_token"] = r[1]
    if len(r) > 2 and r[2]:
        d["participant_token"] = r[2]
    if len(r) > 3 and r[3] is not None:
        d["owner_user_id"] = r[3]
    if len(r) > 4 and r[4] is not None:
        d["version"] = int(r[4])
    return d


def load_all_bills() -> dict[str, dict]:
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            try:
                cursor = client.execute(
                    "SELECT id, data, host_token, participant_token, owner_user_id, version FROM bills"
                )
                rows = cursor.fetchall()
                bills: dict[str, dict] = {}
                for row in rows:
                    try:
                        bill_id = row[0]
                        bill_data = json.loads(row[1])
                        bill_data = _merge_bill_row(bill_data, row)
                        bill_data, changed = normalize_bill_row_data(bill_data)
                        if changed:
                            save_bill(bill_id, bill_data)
                        bills[bill_id] = bill_data
                    except (json.JSONDecodeError, IndexError, TypeError):
                        continue
                return bills
            except Exception:
                import traceback

                traceback.print_exc()
    try:
        if os.path.exists(BILLS_FILE):
            with open(BILLS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
                out = {}
                for bid, bill_data in raw.items():
                    if isinstance(bill_data, dict):
                        d, changed = normalize_bill_row_data(bill_data)
                        if changed:
                            save_bill(bid, d)
                        out[bid] = d
                return out
    except Exception:
        import traceback

        traceback.print_exc()
    return {}


def get_bill(bill_id: str) -> Optional[dict]:
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            try:
                cursor = client.execute(
                    "SELECT data, host_token, participant_token, owner_user_id, version FROM bills WHERE id = ?",
                    (bill_id,),
                )
                rows = cursor.fetchall()
                if rows:
                    r = rows[0]
                    bill_data = json.loads(r[0])
                    bill_data = _merge_bill_data_row(bill_data, r)
                    bill_data, changed = normalize_bill_row_data(bill_data)
                    if changed:
                        save_bill(bill_id, bill_data)
                    return bill_data
            except Exception:
                import traceback

                traceback.print_exc()
    if os.path.exists(BILLS_FILE):
        try:
            with open(BILLS_FILE, "r", encoding="utf-8") as f:
                bills = json.load(f)
                b = bills.get(bill_id)
                if isinstance(b, dict):
                    d, changed = normalize_bill_row_data(b)
                    if changed:
                        save_bill(bill_id, d)
                    return d
        except Exception:
            pass
    return None


def get_bill_by_host_token(host_token: str) -> Optional[dict]:
    if not host_token:
        return None
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            try:
                cursor = client.execute(
                    "SELECT id, data, host_token, participant_token, owner_user_id, version FROM bills WHERE host_token = ?",
                    (host_token,),
                )
                rows = cursor.fetchall()
                if rows:
                    return get_bill(rows[0][0])
            except Exception:
                pass
    for bid, data in load_all_bills().items():
        if data.get("host_token") == host_token:
            return get_bill(bid)
    return None


def get_bill_by_participant_token(participant_token: str) -> Optional[dict]:
    if not participant_token:
        return None
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            try:
                cursor = client.execute(
                    "SELECT id FROM bills WHERE participant_token = ?",
                    (participant_token,),
                )
                rows = cursor.fetchall()
                if rows:
                    return get_bill(rows[0][0])
            except Exception:
                pass
    for bid, data in load_all_bills().items():
        if data.get("participant_token") == participant_token:
            return get_bill(bid)
    return None


def list_bills_by_owner(user_id: str) -> list[dict]:
    out: list[dict] = []
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            try:
                cursor = client.execute(
                    "SELECT id, data, host_token, participant_token, owner_user_id, version FROM bills WHERE owner_user_id = ? ORDER BY id",
                    (user_id,),
                )
                for row in cursor.fetchall():
                    b = get_bill(row[0])
                    if b:
                        out.append(b)
                return out
            except Exception:
                pass
    for bid, data in load_all_bills().items():
        if data.get("owner_user_id") == user_id:
            row = dict(data)
            row.setdefault("id", bid)
            out.append(row)
    return out


def _bill_index_fields(bill_data: dict) -> tuple:
    return (
        bill_data.get("host_token") or "",
        bill_data.get("participant_token") or "",
        bill_data.get("owner_user_id"),
        int(bill_data.get("version") or 0),
    )


def save_bill(bill_id: str, bill_data: dict, retries: int = 3) -> None:
    last = None
    for attempt in range(retries):
        try:
            if USE_TURSO:
                client = _get_turso_client()
                if not client:
                    raise RuntimeError("Turso client not available")
                bill_data, _ = normalize_bill_row_data(bill_data)
                ht, pt, ou, ver = _bill_index_fields(bill_data)
                payload = json.dumps(bill_data)
                client.execute(
                    """
                    INSERT OR REPLACE INTO bills (id, data, host_token, participant_token, owner_user_id, version)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (bill_id, payload, ht, pt, ou, ver),
                )
                client.commit()
                return
            d, _ = normalize_bill_row_data(bill_data)
            _save_to_file(bill_id, d)
            return
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(0.1 * (attempt + 1))
    raise RuntimeError(f"Failed to save bill {bill_id}: {last}")


def save_bill_with_version(
    bill_id: str, bill_data: dict, expected_version: Optional[int]
) -> int:
    """
    Optimistic lock: if expected_version is not None, must match current DB version.
    Returns new version after save (increments by 1).
    """
    current = get_bill(bill_id)
    cur_ver = int((current or {}).get("version") or 0)
    if expected_version is not None and cur_ver != int(expected_version):
        raise ValueError(f"version_conflict: expected {expected_version} got {cur_ver}")
    new_ver = cur_ver + 1
    bill_data = dict(bill_data)
    bill_data["version"] = new_ver
    save_bill(bill_id, bill_data)
    return new_ver


def delete_bill(bill_id: str) -> None:
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            try:
                client.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
                client.commit()
                return
            except Exception:
                pass
    _delete_from_file(bill_id)


def _save_to_file(bill_id: str, bill_data: dict) -> None:
    os.makedirs(os.path.dirname(BILLS_FILE) or ".", exist_ok=True)
    bills: dict = {}
    if os.path.exists(BILLS_FILE):
        with open(BILLS_FILE, "r", encoding="utf-8") as f:
            bills = json.load(f)
    bills[bill_id] = bill_data
    with open(BILLS_FILE, "w", encoding="utf-8") as f:
        json.dump(bills, f, indent=2)


def _delete_from_file(bill_id: str) -> None:
    try:
        if os.path.exists(BILLS_FILE):
            with open(BILLS_FILE, "r", encoding="utf-8") as f:
                bills = json.load(f)
            if bill_id in bills:
                del bills[bill_id]
                with open(BILLS_FILE, "w", encoding="utf-8") as f:
                    json.dump(bills, f, indent=2)
    except Exception:
        pass


# --- Users / sessions / magic links ---


def create_user(email: str, is_admin: bool = False) -> dict:
    e = email.strip().lower()
    existing = get_user_by_email(e)
    if existing:
        return existing
    uid = str(uuid.uuid4())
    row = {
        "id": uid,
        "email": e,
        "is_admin": is_admin,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            client.execute(
                "INSERT INTO users (id, email, is_admin, created_at) VALUES (?, ?, ?, ?)",
                (uid, e, 1 if is_admin else 0, row["created_at"]),
            )
            client.commit()
            got = get_user_by_email(e)
            if got:
                return got
    store = _load_auth_file()
    store["users"][uid] = row
    _save_auth_file(store)
    return row


def get_user_by_email(email: str) -> Optional[dict]:
    e = email.strip().lower()
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            cur = client.execute(
                "SELECT id, email, is_admin, created_at FROM users WHERE email = ?", (e,)
            )
            r = cur.fetchall()
            if r:
                return {
                    "id": r[0][0],
                    "email": r[0][1],
                    "is_admin": bool(r[0][2]),
                    "created_at": r[0][3],
                }
    for u in _load_auth_file()["users"].values():
        if u.get("email") == e:
            return u
    return None


def set_user_admin(email: str, is_admin: bool = True) -> None:
    """Ensure user row has is_admin flag (Turso or local auth file)."""
    e = email.strip().lower()
    flag = 1 if is_admin else 0
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            client.execute(
                "UPDATE users SET is_admin = ? WHERE email = ?",
                (flag, e),
            )
            client.commit()
            return
    store = _load_auth_file()
    for uid, row in store["users"].items():
        if (row.get("email") or "").lower() == e:
            row["is_admin"] = bool(is_admin)
            store["users"][uid] = row
            _save_auth_file(store)
            return


def get_user_by_id(user_id: str) -> Optional[dict]:
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            cur = client.execute(
                "SELECT id, email, is_admin, created_at FROM users WHERE id = ?", (user_id,)
            )
            r = cur.fetchall()
            if r:
                return {
                    "id": r[0][0],
                    "email": r[0][1],
                    "is_admin": bool(r[0][2]),
                    "created_at": r[0][3],
                }
    return _load_auth_file()["users"].get(user_id)


def create_session(user_id: str, ttl_seconds: int = 60 * 60 * 24 * 14) -> str:
    token = secrets.token_urlsafe(32)
    exp = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    exp_iso = exp.isoformat().replace("+00:00", "Z")
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            client.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, exp_iso),
            )
            client.commit()
            return token
    store = _load_auth_file()
    store["sessions"][token] = {"user_id": user_id, "expires_at": exp_iso}
    _save_auth_file(store)
    return token


def _session_expired(exp_iso: str) -> bool:
    if not exp_iso or not str(exp_iso).strip():
        return False
    try:
        s = str(exp_iso).strip()
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        elif "+" in s:
            dt = datetime.fromisoformat(s)
        else:
            dt = datetime.fromisoformat(s + "+00:00")
        return dt.timestamp() < datetime.now(timezone.utc).timestamp()
    except Exception:
        return True


def get_session_user_id(token: str) -> Optional[str]:
    if not token:
        return None
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            cur = client.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token = ?", (token,)
            )
            r = cur.fetchall()
            if not r:
                return None
            exp = str(r[0][1] or "")
            if _session_expired(exp):
                client.execute("DELETE FROM sessions WHERE token = ?", (token,))
                client.commit()
                return None
            return str(r[0][0])
    s = _load_auth_file()["sessions"].get(token)
    if not s:
        return None
    if _session_expired(str(s.get("expires_at") or "")):
        delete_session(token)
        return None
    return str(s.get("user_id"))


def delete_session(token: str) -> None:
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            client.execute("DELETE FROM sessions WHERE token = ?", (token,))
            client.commit()
            return
    store = _load_auth_file()
    store["sessions"].pop(token, None)
    _save_auth_file(store)


def store_magic_link(email: str, raw_token: str, ttl_seconds: int = 900) -> str:
    link_id = str(uuid.uuid4())
    th = hashlib.sha256(raw_token.encode()).hexdigest()
    exp = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    exp_iso = exp.isoformat().replace("+00:00", "Z")
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            client.execute(
                "INSERT INTO magic_links (id, email, token_hash, expires_at, used_at) VALUES (?, ?, ?, ?, NULL)",
                (link_id, email.strip().lower(), th, exp_iso),
            )
            client.commit()
            return link_id
    store = _load_auth_file()
    store["magic_links"][link_id] = {
        "email": email.strip().lower(),
        "token_hash": th,
        "expires_at": exp_iso,
        "used_at": None,
    }
    _save_auth_file(store)
    return link_id


def consume_magic_link(raw_token: str) -> Optional[str]:
    th = hashlib.sha256(raw_token.encode()).hexdigest()
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            cur = client.execute(
                "SELECT id, email, expires_at, used_at FROM magic_links WHERE token_hash = ?",
                (th,),
            )
            rows = cur.fetchall()
            if not rows:
                return None
            row = rows[0]
            if row[3]:
                return None
            if _session_expired(str(row[2] or "")):
                return None
            used = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            client.execute(
                "UPDATE magic_links SET used_at = ? WHERE id = ?",
                (used, row[0]),
            )
            client.commit()
            return str(row[1])
    store = _load_auth_file()
    for mid, ml in list(store["magic_links"].items()):
        if ml.get("token_hash") == th and not ml.get("used_at"):
            if _session_expired(str(ml.get("expires_at") or "")):
                return None
            ml["used_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            store["magic_links"][mid] = ml
            _save_auth_file(store)
            return str(ml.get("email"))
    return None


def list_all_bill_summaries() -> list[dict]:
    """Admin: summaries from DB."""
    out = []
    for bid, data in load_all_bills().items():
        out.append(
            {
                "id": bid,
                "title": data.get("title"),
                "items_count": len(data.get("items") or []),
                "people_count": len(data.get("people") or []),
                "total": data.get("total"),
                "status": data.get("status"),
                "created_at": data.get("created_at"),
            }
        )
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out
