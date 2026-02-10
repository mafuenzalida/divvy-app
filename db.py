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
            import libsql_experimental as libsql
            if not TURSO_DATABASE_URL or not TURSO_AUTH_TOKEN:
                print("⚠️ Turso credentials not configured")
                return None
            _turso_client = libsql.connect(
                TURSO_DATABASE_URL,
                auth_token=TURSO_AUTH_TOKEN
            )
            # Ensure table exists
            _turso_client.execute("""
                CREATE TABLE IF NOT EXISTS bills (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
            """)
            _turso_client.commit()
            print("✅ Connected to Turso database")
        except ImportError:
            print("⚠️ libsql_experimental not installed. Install with: pip install libsql-experimental")
            return None
        except Exception as e:
            print(f"⚠️ Turso connection failed: {e}")
            import traceback
            traceback.print_exc()
            return None
    return _turso_client


def load_all_bills() -> dict:
    """Load all bills from storage. Returns empty dict on error."""
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            try:
                cursor = client.execute("SELECT id, data FROM bills")
                rows = cursor.fetchall()
                bills = {}
                for row in rows:
                    try:
                        bill_id = row[0]
                        bill_data = json.loads(row[1])
                        bills[bill_id] = bill_data
                    except (json.JSONDecodeError, IndexError) as e:
                        print(f"⚠️ Error parsing bill row: {e}")
                        continue
                print(f"✅ Loaded {len(bills)} bills from Turso")
                return bills
            except Exception as e:
                print(f"❌ Error loading from Turso: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("⚠️ Turso client not available, falling back to local file")
    
    # Fallback to JSON file
    try:
        if os.path.exists(BILLS_FILE):
            with open(BILLS_FILE, 'r') as f:
                bills = json.load(f)
                print(f"✅ Loaded {len(bills)} bills from {BILLS_FILE}")
                return bills
        else:
            print(f"ℹ️ No local file found at {BILLS_FILE}")
    except Exception as e:
        print(f"❌ Error loading bills from file: {e}")
        import traceback
        traceback.print_exc()
    
    print("⚠️ No bills loaded, returning empty dict")
    return {}


def get_bill(bill_id: str) -> dict:
    """Get a single bill from storage (fresh from DB). Returns None if not found."""
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            try:
                print(f"🔍 Fetching bill {bill_id} from Turso...")
                cursor = client.execute("SELECT data FROM bills WHERE id = ?", (bill_id,))
                rows = cursor.fetchall()
                if rows and len(rows) > 0:
                    try:
                        bill_data = json.loads(rows[0][0])
                        print(f"✅ Found bill {bill_id} in Turso")
                        return bill_data
                    except json.JSONDecodeError as e:
                        print(f"❌ Error parsing bill {bill_id} data: {e}")
                        return None
                else:
                    print(f"❌ Bill {bill_id} not found in Turso")
            except Exception as e:
                print(f"⚠️ Error getting bill from Turso: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"⚠️ No Turso client available for get_bill")
    
    # Fallback to JSON file
    try:
        if os.path.exists(BILLS_FILE):
            with open(BILLS_FILE, 'r') as f:
                bills = json.load(f)
                bill = bills.get(bill_id)
                if bill:
                    print(f"✅ Found bill {bill_id} in local file")
                return bill
    except Exception as e:
        print(f"❌ Error getting bill from file: {e}")
        import traceback
        traceback.print_exc()
    
    return None


def save_bill(bill_id: str, bill_data: dict, retries: int = 3):
    """Save a single bill to storage. Raises exception on failure to ensure data integrity.
    
    Args:
        bill_id: The bill ID to save
        bill_data: The bill data as a dict
        retries: Number of retry attempts for transient failures
        
    Raises:
        Exception: If save fails after all retries
    """
    last_error = None
    
    for attempt in range(retries):
        try:
            if USE_TURSO:
                client = _get_turso_client()
                if not client:
                    raise Exception("Turso client not available")
                
                data_json = json.dumps(bill_data)
                client.execute(
                    "INSERT OR REPLACE INTO bills (id, data) VALUES (?, ?)",
                    (bill_id, data_json)
                )
                client.commit()
                print(f"✅ Successfully saved bill {bill_id} to Turso (attempt {attempt + 1})")
                return  # Success!
            
            # Fallback to JSON file
            _save_to_file(bill_id, bill_data)
            print(f"✅ Successfully saved bill {bill_id} to local file")
            return  # Success!
            
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                print(f"⚠️ Error saving bill {bill_id} (attempt {attempt + 1}/{retries}): {e}. Retrying...")
                import time
                time.sleep(0.1 * (attempt + 1))  # Exponential backoff
            else:
                print(f"❌ CRITICAL: Failed to save bill {bill_id} after {retries} attempts: {e}")
    
    # If we get here, all retries failed
    raise Exception(f"Failed to save bill {bill_id} to database after {retries} attempts: {last_error}")


def delete_bill(bill_id: str):
    """Delete a bill from storage."""
    if USE_TURSO:
        client = _get_turso_client()
        if client:
            try:
                client.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
                client.commit()
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
