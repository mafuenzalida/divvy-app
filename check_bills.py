#!/usr/bin/env python3
"""
Script to inspect bills in Turso database.
Useful for debugging lost updates.
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

if not TURSO_DATABASE_URL or not TURSO_AUTH_TOKEN:
    print("❌ TURSO_DATABASE_URL and TURSO_AUTH_TOKEN must be set in .env")
    exit(1)

try:
    import libsql_experimental as libsql
    
    print(f"🔗 Connecting to Turso...")
    client = libsql.connect(TURSO_DATABASE_URL, auth_token=TURSO_AUTH_TOKEN)
    
    # List all bills
    print("\n📋 All Bills in Database:")
    print("=" * 80)
    cursor = client.execute("SELECT id, data FROM bills ORDER BY id")
    rows = cursor.fetchall()
    
    if not rows:
        print("No bills found in database.")
    else:
        for row in rows:
            bill_id = row[0]
            bill_data = json.loads(row[1])
            
            print(f"\n🆔 Bill ID: {bill_id}")
            print(f"   Title: {bill_data.get('title', 'N/A')}")
            print(f"   People: {', '.join(bill_data.get('people', []))}")
            print(f"   Items: {len(bill_data.get('items', []))}")
            print(f"   Total: ${bill_data.get('total', 0):,.0f}")
            print(f"   Status: {bill_data.get('status', 'N/A')}")
            print(f"   Created: {bill_data.get('created_at', 'N/A')}")
            print(f"   Locked: {bill_data.get('locked', False)}")
            
            # Show item assignments
            items = bill_data.get('items', [])
            if items:
                print(f"   Item Assignments:")
                for item in items:
                    assigned = item.get('assigned_to', [])
                    if assigned:
                        print(f"     - {item.get('name', 'N/A')}: {', '.join(assigned)}")
    
    # If a specific bill ID is provided, show full details
    import sys
    if len(sys.argv) > 1:
        bill_id = sys.argv[1]
        print(f"\n\n🔍 Full Details for Bill {bill_id}:")
        print("=" * 80)
        cursor = client.execute("SELECT data FROM bills WHERE id = ?", [bill_id])
        rows = cursor.fetchall()
        if rows:
            bill_data = json.loads(rows[0][0])
            print(json.dumps(bill_data, indent=2, ensure_ascii=False))
        else:
            print(f"Bill {bill_id} not found.")
    
    client.close()
    print("\n✅ Done!")
    
except ImportError:
    print("❌ libsql_experimental not installed. Install with: pip install libsql-experimental")
except Exception as e:
    print(f"❌ Error: {e}")
