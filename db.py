"""
Database adapter for CobroF (Divvy)
- Uses Turso (libsql) in production when TURSO_DATABASE_URL is set
- Falls back to local JSON file for local development
"""

import os
import json
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

# Determine storage mode
USE_TURSO = bool(TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)

# Local file fallback
BILLS_FILE = "data/bills.json"

# Turso client (lazy init)
_turso_client = None


def _get_turso_client():
    """Get or create Turso client (lazy initialization)."""
    global _turso_client
    if _turso_client is None and USE_TURSO:
        try:
            from libsql_client import create_client_sync
            _turso_client = create_client_sync(
                url=TURSO_DATABASE_URL,
                auth_token=TURSO_AUTH_TOKEN
            )
            # Ensure table exists
            _turso_client.execute("""
                CREATE TABLE IF NOT EXISTS bills (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
            """)
            print("✅ Connected to Turso database")
        except Exception as e:
            print(f"⚠️ Turso connection failed: {e}")
            return None
    return _turso_client


def load_all_bills() -> dict:
    """Load all bills from storage."""
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            try:
                result = client.execute("SELECT id, data FROM bills")
                bills = {}
                for row in result.rows:
                    bill_id = row[0]
                    bill_data = json.loads(row[1])
                    bills[bill_id] = bill_data
                print(f"Loaded {len(bills)} bills from Turso")
                return bills
            except Exception as e:
                print(f"Error loading from Turso: {e}")
    
    # Fallback to JSON file
    try:
        if os.path.exists(BILLS_FILE):
            with open(BILLS_FILE, 'r') as f:
                bills = json.load(f)
                print(f"Loaded {len(bills)} bills from {BILLS_FILE}")
                return bills
    except Exception as e:
        print(f"Error loading bills from file: {e}")
    
    return {}


def save_bill(bill_id: str, bill_data: dict):
    """Save a single bill to storage."""
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            try:
                data_json = json.dumps(bill_data)
                client.execute(
                    "INSERT OR REPLACE INTO bills (id, data) VALUES (?, ?)",
                    [bill_id, data_json]
                )
                return
            except Exception as e:
                print(f"Error saving to Turso: {e}")
    
    # Fallback to JSON file
    _save_to_file(bill_id, bill_data)


def delete_bill(bill_id: str):
    """Delete a bill from storage."""
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            try:
                client.execute("DELETE FROM bills WHERE id = ?", [bill_id])
                return
            except Exception as e:
                print(f"Error deleting from Turso: {e}")
    
    # Fallback: reload, remove, save
    _delete_from_file(bill_id)


def _save_to_file(bill_id: str, bill_data: dict):
    """Save bill to local JSON file."""
    try:
        os.makedirs(os.path.dirname(BILLS_FILE), exist_ok=True)
        bills = {}
        if os.path.exists(BILLS_FILE):
            with open(BILLS_FILE, 'r') as f:
                bills = json.load(f)
        bills[bill_id] = bill_data
        with open(BILLS_FILE, 'w') as f:
            json.dump(bills, f, indent=2)
    except Exception as e:
        print(f"Error saving to file: {e}")


def _delete_from_file(bill_id: str):
    """Delete bill from local JSON file."""
    try:
        if os.path.exists(BILLS_FILE):
            with open(BILLS_FILE, 'r') as f:
                bills = json.load(f)
            if bill_id in bills:
                del bills[bill_id]
                with open(BILLS_FILE, 'w') as f:
                    json.dump(bills, f, indent=2)
    except Exception as e:
        print(f"Error deleting from file: {e}")


def get_storage_mode() -> str:
    """Return current storage mode for status endpoint."""
    return "turso" if USE_TURSO else "local_file"
