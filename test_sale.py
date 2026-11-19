"""
Test the sticker server with fake sale data.
Run this AFTER sticker_server.py is already running.

Usage:
    python test_sale.py
"""

import json
import urllib.request

STICKER_SERVER = "http://localhost:9876"

# Simulated sale matching the CISePOS API format
test_sale = {
    "request": {
        "PartyName": "Awais Ali",
        "DailyBillNo": "99",
    },
    "response": {
        "status": True,
        "master": {
            "BillNo": "TEST-001/108Ji",
            "DailyBillNo": "99",
            "TotalQuantity": "5",
            "BillDate": "2026-11-19 16:00:00",
            "OrderTypeID": 1,
        },
        "detail": [
            {
                "ItemName": "Ice Fresh Passion Fruit Tea",
                "Quantity": "1",
                "Rate": 400,
                "Amount": 400,
                "SerialNo": 1,
            },
            {
                "ItemName": "Chocolate Oreo Smoothie Snow Top",
                "Quantity": "1",
                "Rate": 500,
                "Amount": 500,
                "SerialNo": 2,
            },
            {
                "ItemName": "Original Ice Cream",
                "Quantity": "2",
                "Rate": 200,
                "Amount": 400,
                "SerialNo": 3,
            },
            {
                "ItemName": "white spoon",
                "Quantity": "3",
                "Rate": 20,
                "Amount": 60,
                "SerialNo": 4,
            },
        ],
    },
}

# Send to server
data = json.dumps(test_sale).encode("utf-8")
req = urllib.request.Request(
    f"{STICKER_SERVER}/new-sale",
    data=data,
    headers={"Content-Type": "application/json"},
)

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
        print("Server response:", json.dumps(result, indent=2))
        if result.get("status") == "ok":
            print(f"\n✅ {result['stickers_printed']} sticker(s) printed, {result['items_skipped']} item(s) skipped")
        else:
            print(f"\n⚠️  {result}")
except urllib.error.URLError as e:
    print(f"❌ Could not reach sticker server: {e}")
    print("   Make sure sticker_server.py is running first.")
