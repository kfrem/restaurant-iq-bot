"""
demo_setup.py — Standalone script to pre-populate the database with demo data.

Run this ONCE before the client demo to make sure the database is ready:
    python demo_setup.py

Then in Telegram:
    1. /demo  — loads demo data into the bot for the active chat
    2. Send a text/voice message — watch live AI analysis
    3. /status — see weekly entry counts
    4. /weeklyreport — generate full briefing + PDF

Reset at any time:
    /demoreset  (from Telegram)
    or:  python demo_setup.py --reset
"""

import sys
import json
from database import init_db, register_restaurant, register_staff, get_connection
from demo_data import get_demo_entries, DEMO_STAFF

DEMO_CHAT_ID = "DEMO_STANDALONE"
DEMO_OWNER_ID = "DEMO_OWNER"
DEMO_RESTAURANT_NAME = "The Golden Fork"


def reset_demo():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM restaurants WHERE telegram_group_id = ?", (DEMO_CHAT_ID,))
    row = cur.fetchone()
    if not row:
        print("No standalone demo data found.")
        conn.close()
        return
    rid = row["id"]
    cur.execute("DELETE FROM daily_entries WHERE restaurant_id = ?", (rid,))
    cur.execute("DELETE FROM weekly_reports WHERE restaurant_id = ?", (rid,))
    cur.execute("DELETE FROM staff WHERE restaurant_id = ?", (rid,))
    cur.execute("DELETE FROM restaurants WHERE id = ?", (rid,))
    conn.commit()
    conn.close()
    print("Demo data removed.")


def setup_demo():
    init_db()

    # Remove any previous standalone demo
    reset_demo()

    # Register demo restaurant
    register_restaurant(DEMO_RESTAURANT_NAME, DEMO_CHAT_ID, DEMO_OWNER_ID)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM restaurants WHERE telegram_group_id = ?", (DEMO_CHAT_ID,))
    row = cur.fetchone()
    if not row:
        print("ERROR: Could not create demo restaurant.")
        conn.close()
        return
    restaurant_id = row["id"]

    # Register staff
    staff_map: dict[str, int] = {}
    for i, member in enumerate(DEMO_STAFF):
        fake_user_id = f"DEMO_STAFF_{i}_{restaurant_id}"
        register_staff(restaurant_id, fake_user_id, member["name"], member["role"])
        cur.execute(
            "SELECT id FROM staff WHERE restaurant_id = ? AND telegram_user_id = ?",
            (restaurant_id, fake_user_id),
        )
        s = cur.fetchone()
        if s:
            staff_map[member["name"]] = s["id"]

    # Insert demo entries
    entries = get_demo_entries()
    for e in entries:
        staff_id = staff_map.get(e["staff_name"], list(staff_map.values())[0])
        cur.execute(
            """INSERT INTO daily_entries
               (restaurant_id, staff_id, entry_date, entry_time, entry_type,
                raw_text, structured_data, category)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                restaurant_id,
                staff_id,
                e["entry_date"],
                e["entry_time"],
                e["entry_type"],
                e["raw_text"],
                e["structured_data"],
                e["category"],
            ),
        )
    conn.commit()
    conn.close()

    # Print summary
    categories: dict = {}
    for e in entries:
        cat = e["category"]
        categories[cat] = categories.get(cat, 0) + 1

    print(f"\nDemo data loaded for: {DEMO_RESTAURANT_NAME}")
    print("=" * 40)
    print(f"\nStaff: {', '.join(m['name'] for m in DEMO_STAFF)}")
    print(f"\n{len(entries)} entries this week:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")
    print("\nReady! In Telegram:")
    print("  /demo         — load into active chat")
    print("  /status       — see entry summary")
    print("  /weeklyreport — generate full report + PDF")
    print("\nOr generate report directly:")
    print("  python -c \"")
    print("  from database import get_entries_for_period")
    print("  from analyzer import generate_weekly_report")
    print("  from report_generator import generate_pdf_report")
    print("  import json")
    print("  # then call generate_weekly_report(entries, name)")
    print("  \"")


if __name__ == "__main__":
    if "--reset" in sys.argv:
        reset_demo()
    else:
        setup_demo()
