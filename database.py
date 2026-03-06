import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with _db() as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS restaurants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                telegram_group_id TEXT UNIQUE,
                owner_telegram_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS staff (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER,
                telegram_user_id TEXT,
                name TEXT,
                role TEXT DEFAULT 'staff',
                UNIQUE(restaurant_id, telegram_user_id),
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER NOT NULL,
                staff_id INTEGER,
                entry_date TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                entry_type TEXT NOT NULL,
                raw_text TEXT,
                structured_data TEXT,
                category TEXT DEFAULT 'general',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id),
                FOREIGN KEY (staff_id) REFERENCES staff(id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS weekly_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                week_end TEXT NOT NULL,
                report_text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
            )
        """)

        # Invoice tracking — populated whenever a photo invoice is saved.
        # Enables payment reminders, outstanding balance tracking, and P&L.
        c.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER NOT NULL,
                entry_id INTEGER,
                supplier_name TEXT,
                invoice_date TEXT,
                due_date TEXT,
                total_amount REAL,
                vat REAL,
                description TEXT,
                paid INTEGER DEFAULT 0,
                paid_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id),
                FOREIGN KEY (entry_id) REFERENCES daily_entries(id)
            )
        """)

        conn.commit()
    print("Database initialised.")


def register_restaurant(name: str, group_id: str, owner_id: str) -> int:
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO restaurants (name, telegram_group_id, owner_telegram_id) VALUES (?, ?, ?)",
            (name, group_id, owner_id),
        )
        conn.commit()
        c.execute("SELECT id FROM restaurants WHERE telegram_group_id = ?", (group_id,))
        row = c.fetchone()
    return row["id"] if row else None


def update_restaurant_name(group_id: str, name: str):
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE restaurants SET name = ? WHERE telegram_group_id = ?",
            (name, group_id),
        )
        conn.commit()


def get_restaurant_by_group(group_id: str):
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM restaurants WHERE telegram_group_id = ?", (str(group_id),))
        return c.fetchone()


def register_staff(restaurant_id: int, telegram_user_id: str, name: str, role: str = "staff"):
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO staff (restaurant_id, telegram_user_id, name, role) VALUES (?, ?, ?, ?)",
            (restaurant_id, str(telegram_user_id), name, role),
        )
        conn.commit()


def get_staff(telegram_user_id: str, restaurant_id: int):
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM staff WHERE telegram_user_id = ? AND restaurant_id = ?",
            (str(telegram_user_id), restaurant_id),
        )
        return c.fetchone()


def get_or_register_staff(restaurant_id: int, telegram_user_id: str, name: str, role: str = "staff"):
    """Get a staff member, creating them if they don't exist yet. Always 2 DB ops max."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO staff (restaurant_id, telegram_user_id, name, role) VALUES (?, ?, ?, ?)",
            (restaurant_id, str(telegram_user_id), name, role),
        )
        conn.commit()
        c.execute(
            "SELECT * FROM staff WHERE telegram_user_id = ? AND restaurant_id = ?",
            (str(telegram_user_id), restaurant_id),
        )
        return c.fetchone()


def save_entry(restaurant_id: int, staff_id: int, entry_type: str,
               raw_text: str, structured_data: str, category: str):
    with _db() as conn:
        c = conn.cursor()
        now = datetime.now()
        c.execute(
            """INSERT INTO daily_entries
               (restaurant_id, staff_id, entry_date, entry_time, entry_type, raw_text, structured_data, category)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                restaurant_id,
                staff_id,
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S"),
                entry_type,
                raw_text,
                structured_data,
                category,
            ),
        )
        conn.commit()
        return c.lastrowid


def get_entries_for_period(restaurant_id: int, start_date: str, end_date: str):
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT * FROM daily_entries
               WHERE restaurant_id = ? AND entry_date BETWEEN ? AND ?
               ORDER BY entry_date, entry_time""",
            (restaurant_id, start_date, end_date),
        )
        return c.fetchall()


def get_entries_with_staff(restaurant_id: int, start_date: str, end_date: str):
    """Like get_entries_for_period but includes staff name and role via JOIN."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT daily_entries.*, staff.name as staff_name, staff.role as staff_role
               FROM daily_entries
               LEFT JOIN staff ON daily_entries.staff_id = staff.id
               WHERE daily_entries.restaurant_id = ? AND entry_date BETWEEN ? AND ?
               ORDER BY entry_date, entry_time""",
            (restaurant_id, start_date, end_date),
        )
        return c.fetchall()


def get_week_entries(restaurant_id: int):
    now = datetime.now()
    start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    return get_entries_for_period(restaurant_id, start, end)


def get_restaurant_count() -> int:
    """Return the total number of registered restaurants across all groups."""
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as total FROM restaurants")
        row = c.fetchone()
    return row["total"] if row else 0


def save_weekly_report(restaurant_id: int, week_start: str, week_end: str, report_text: str):
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO weekly_reports (restaurant_id, week_start, week_end, report_text)
               VALUES (?, ?, ?, ?)""",
            (restaurant_id, week_start, week_end, report_text),
        )
        conn.commit()


# ── Invoice tracking ──────────────────────────────────────────────────────────

def save_invoice(restaurant_id: int, entry_id: int, supplier_name: str,
                 invoice_date: str, due_date: str, total_amount: float,
                 vat: float, description: str):
    """Record an invoice for payment tracking and P&L. Called after every photo invoice."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO invoices
               (restaurant_id, entry_id, supplier_name, invoice_date, due_date,
                total_amount, vat, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (restaurant_id, entry_id, supplier_name, invoice_date, due_date,
             total_amount, vat, description),
        )
        conn.commit()
        return c.lastrowid


def get_outstanding_invoices(restaurant_id: int) -> list:
    """Return all unpaid invoices sorted by due date (most urgent first)."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT * FROM invoices
               WHERE restaurant_id = ? AND paid = 0
               ORDER BY due_date ASC NULLS LAST""",
            (restaurant_id,),
        )
        return c.fetchall()


def mark_invoice_paid(invoice_id: int) -> bool:
    """Mark an invoice as paid. Returns True if a record was updated."""
    with _db() as conn:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute(
            "UPDATE invoices SET paid = 1, paid_date = ? WHERE id = ?",
            (today, invoice_id),
        )
        conn.commit()
        return c.rowcount > 0


def get_invoices_due_soon(days_ahead: int = 3) -> list:
    """Return unpaid invoices across ALL restaurants that are due within days_ahead days.
    Used by the daily reminder scheduler."""
    with _db() as conn:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cutoff = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
        c.execute(
            """SELECT i.*, r.telegram_group_id, r.name as restaurant_name
               FROM invoices i
               JOIN restaurants r ON i.restaurant_id = r.id
               WHERE i.paid = 0 AND i.due_date IS NOT NULL AND i.due_date <= ?
               ORDER BY i.due_date ASC""",
            (cutoff,),
        )
        return c.fetchall()


def get_financial_summary(restaurant_id: int, start_date: str, end_date: str) -> dict:
    """
    Calculate revenue, cost totals and gross profit from entries in a period.
    Revenue comes from structured_data.revenue fields on revenue-category entries.
    Costs come from structured_data.total_amount fields on cost-category photo entries.
    Returns a dict with totals and itemised cost list.
    """
    entries = get_entries_for_period(restaurant_id, start_date, end_date)

    revenue_total = 0.0
    cost_total = 0.0
    cost_items = []

    for e in entries:
        if not e["structured_data"]:
            continue
        try:
            data = json.loads(e["structured_data"])
        except (json.JSONDecodeError, TypeError):
            continue

        if e["category"] == "revenue" and data.get("revenue"):
            try:
                revenue_total += float(data["revenue"])
            except (TypeError, ValueError):
                pass

        if e["category"] == "cost" and data.get("total_amount"):
            try:
                amount = float(data["total_amount"])
                cost_total += amount
                cost_items.append({
                    "supplier": data.get("supplier_name", "Unknown"),
                    "amount": amount,
                    "date": e["entry_date"],
                    "description": data.get("summary", ""),
                })
            except (TypeError, ValueError):
                pass

    gross_profit = revenue_total - cost_total
    gross_margin = round(gross_profit / revenue_total * 100, 1) if revenue_total else 0.0

    return {
        "period_start": start_date,
        "period_end": end_date,
        "revenue_total": round(revenue_total, 2),
        "cost_total": round(cost_total, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_margin_pct": gross_margin,
        "cost_items": cost_items,
    }
