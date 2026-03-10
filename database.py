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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                legal_name TEXT,
                address TEXT,
                city TEXT,
                postcode TEXT,
                phone TEXT,
                email TEXT,
                website TEXT,
                company_number TEXT,
                vat_number TEXT,
                cuisine_type TEXT,
                num_covers INTEGER,
                num_branches INTEGER,
                profile_complete INTEGER DEFAULT 0
            )
        """)

        # Migrate older databases that don't have the profile columns yet
        _profile_cols = [
            ("legal_name", "TEXT"), ("address", "TEXT"), ("city", "TEXT"),
            ("postcode", "TEXT"), ("phone", "TEXT"), ("email", "TEXT"),
            ("website", "TEXT"), ("company_number", "TEXT"), ("vat_number", "TEXT"),
            ("cuisine_type", "TEXT"), ("num_covers", "INTEGER"),
            ("num_branches", "INTEGER"), ("profile_complete", "INTEGER DEFAULT 0"),
            # TradeFlow: multi-currency support
            ("currency_code", "TEXT DEFAULT 'GBP'"),
            ("currency_symbol", "TEXT DEFAULT '£'"),
            ("industry", "TEXT DEFAULT 'restaurant'"),
        ]
        for col, col_type in _profile_cols:
            try:
                c.execute(f"ALTER TABLE restaurants ADD COLUMN {col} {col_type}")
            except Exception:
                pass  # column already exists

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

        # Tips Act compliance log — Employment (Allocation of Tips) Act 2023.
        # Every tip event detected from voice/text/photo is recorded here.
        # Restaurants must keep 3-year records and allow staff to request them.
        c.execute("""
            CREATE TABLE IF NOT EXISTS tips_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER NOT NULL,
                entry_id INTEGER,
                event_date TEXT NOT NULL,
                shift TEXT,
                tip_type TEXT DEFAULT 'card',
                gross_amount REAL,
                staff_notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id),
                FOREIGN KEY (entry_id) REFERENCES daily_entries(id)
            )
        """)

        # Allergen alerts — Natasha's Law (2021) traceability log.
        # Flagged whenever a supplier change or ingredient substitution is detected.
        c.execute("""
            CREATE TABLE IF NOT EXISTS allergen_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER NOT NULL,
                entry_id INTEGER,
                alert_date TEXT NOT NULL,
                supplier_name TEXT,
                product_name TEXT,
                allergen_concern TEXT,
                resolved INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id),
                FOREIGN KEY (entry_id) REFERENCES daily_entries(id)
            )
        """)

        # Labour cost entries — wages, agency staff, contractor payments.
        # Captured via /labour command or auto-detected from voice/text.
        # Critical for true P&L: labour is typically 28-35% of revenue.
        c.execute("""
            CREATE TABLE IF NOT EXISTS labour_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER NOT NULL,
                entry_id INTEGER,
                labour_date TEXT NOT NULL,
                shift TEXT,
                amount REAL NOT NULL,
                hours REAL,
                description TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id),
                FOREIGN KEY (entry_id) REFERENCES daily_entries(id)
            )
        """)

        # Supplier price points — one row per line item per invoice.
        # Enables price trend detection: flags increases vs. historical average.
        c.execute("""
            CREATE TABLE IF NOT EXISTS invoice_line_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER NOT NULL,
                invoice_id INTEGER,
                supplier_name TEXT NOT NULL,
                item_name TEXT NOT NULL,
                unit_price REAL,
                quantity REAL,
                unit TEXT,
                recorded_date TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id),
                FOREIGN KEY (invoice_id) REFERENCES invoices(id)
            )
        """)

        # Support tickets — allows restaurants to report issues to the app owner
        # and receive replies without phone calls.
        c.execute("""
            CREATE TABLE IF NOT EXISTS support_tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER NOT NULL,
                chat_id TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                owner_reply TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
            )
        """)

        # Stock par levels — one row per item per restaurant.
        # par_level is the minimum quantity that should always be on hand.
        # current_level is the last count recorded by staff.
        # Items where current_level < par_level are flagged as low stock.
        c.execute("""
            CREATE TABLE IF NOT EXISTS stock_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                par_level REAL NOT NULL DEFAULT 0,
                unit TEXT DEFAULT '',
                current_level REAL,
                last_count_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(restaurant_id, item_name),
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
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


def update_restaurant_profile(group_id: str, **fields):
    """Update any subset of profile fields for a restaurant.
    Allowed keys: legal_name, address, city, postcode, phone, email,
    website, company_number, vat_number, cuisine_type, num_covers,
    num_branches, profile_complete.
    """
    allowed = {
        "legal_name", "address", "city", "postcode", "phone", "email",
        "website", "company_number", "vat_number", "cuisine_type",
        "num_covers", "num_branches", "profile_complete",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [group_id]
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            f"UPDATE restaurants SET {set_clause} WHERE telegram_group_id = ?",
            values,
        )
        conn.commit()


def get_restaurant_by_group(group_id: str):
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM restaurants WHERE telegram_group_id = ?", (str(group_id),))
        return c.fetchone()


# ── TradeFlow: Multi-currency support ────────────────────────────────────────

# Supported currencies: code → (symbol, display_name)
SUPPORTED_CURRENCIES = {
    "GBP": ("£",    "British Pound"),
    "USD": ("$",    "US Dollar"),
    "EUR": ("€",    "Euro"),
    "NGN": ("₦",   "Nigerian Naira"),
    "KES": ("KSh", "Kenyan Shilling"),
    "ZAR": ("R",   "South African Rand"),
    "GHS": ("GH₵", "Ghanaian Cedi"),
    "UGX": ("USh", "Ugandan Shilling"),
    "TZS": ("TSh", "Tanzanian Shilling"),
    "XOF": ("CFA", "West African CFA Franc"),
}


def get_restaurant_currency(group_id: str) -> tuple[str, str]:
    """Return (currency_code, currency_symbol) for the given group.
    Defaults to GBP / £ if not set or if the restaurant is not found."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT currency_code, currency_symbol FROM restaurants WHERE telegram_group_id = ?",
            (str(group_id),),
        )
        row = c.fetchone()
    if row and row["currency_code"]:
        return row["currency_code"], row["currency_symbol"] or "£"
    return "GBP", "£"


def set_restaurant_currency(group_id: str, currency_code: str) -> tuple[str, str]:
    """Set the currency for a restaurant. Returns (code, symbol).
    Raises ValueError if the currency code is not supported."""
    code = currency_code.upper()
    if code not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Unsupported currency: {code}")
    symbol, _ = SUPPORTED_CURRENCIES[code]
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE restaurants SET currency_code = ?, currency_symbol = ? WHERE telegram_group_id = ?",
            (code, symbol, str(group_id)),
        )
        conn.commit()
    return code, symbol


SUPPORTED_INDUSTRIES = {
    "restaurant": "Restaurant",
    "cafe": "Café",
    "bar": "Bar",
    "pub": "Pub",
    "bakery": "Bakery",
    "food truck": "Food Truck",
    "takeaway": "Takeaway",
    "retail": "Retail Shop",
    "salon": "Salon",
    "barbershop": "Barbershop",
    "gym": "Gym",
    "hotel": "Hotel",
    "spa": "Spa",
    "laundry": "Laundry",
    "pharmacy": "Pharmacy",
    "supermarket": "Supermarket",
    "general": "General Business",
}


def set_restaurant_industry(group_id: str, industry: str) -> str:
    """Set the business type/industry for a restaurant. Returns normalised industry string."""
    normalised = industry.strip().lower()
    # Accept known types or any free text (just store as-is if unknown)
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE restaurants SET industry = ? WHERE telegram_group_id = ?",
            (normalised, str(group_id)),
        )
        conn.commit()
    return normalised


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


def get_last_entry(restaurant_id: int, staff_id: int):
    """Return the most recent entry by this staff member, or None."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT * FROM daily_entries
               WHERE restaurant_id = ? AND staff_id = ?
               ORDER BY id DESC LIMIT 1""",
            (restaurant_id, staff_id),
        )
        return c.fetchone()


def update_entry(entry_id: int, raw_text: str, structured_data: str, category: str):
    """Overwrite an entry's text and AI analysis (used by /correct)."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """UPDATE daily_entries
               SET raw_text = ?, structured_data = ?, category = ?
               WHERE id = ?""",
            (raw_text, structured_data, category, entry_id),
        )
        conn.commit()


def delete_last_entry(restaurant_id: int, staff_id: int):
    """
    Delete the most recent entry by this staff member in this restaurant.
    Returns the deleted entry's raw_text (for confirmation), or None if nothing found.
    """
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT id, raw_text, entry_type FROM daily_entries
               WHERE restaurant_id = ? AND staff_id = ?
               ORDER BY id DESC LIMIT 1""",
            (restaurant_id, staff_id),
        )
        row = c.fetchone()
        if not row:
            return None
        c.execute("DELETE FROM daily_entries WHERE id = ?", (row["id"],))
        conn.commit()
        return {"id": row["id"], "raw_text": row["raw_text"], "entry_type": row["entry_type"]}


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


def get_invoices_for_period(restaurant_id: int, start_date: str, end_date: str) -> list:
    """Return all invoices (paid and unpaid) within a date range, ordered by invoice date."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT * FROM invoices
               WHERE restaurant_id = ? AND invoice_date BETWEEN ? AND ?
               ORDER BY invoice_date ASC""",
            (restaurant_id, start_date, end_date),
        )
        return c.fetchall()


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


# ── Tips Act compliance ───────────────────────────────────────────────────────

def save_tip_event(restaurant_id: int, entry_id: int, event_date: str,
                   shift: str, tip_type: str, gross_amount: float, staff_notes: str):
    """Record a tip event for Tips Act compliance. Called whenever tips are detected."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO tips_log
               (restaurant_id, entry_id, event_date, shift, tip_type, gross_amount, staff_notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (restaurant_id, entry_id, event_date, shift, tip_type, gross_amount, staff_notes),
        )
        conn.commit()
        return c.lastrowid


def get_tips_for_period(restaurant_id: int, start_date: str, end_date: str) -> list:
    """Return all tip events in a date range."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT * FROM tips_log
               WHERE restaurant_id = ? AND event_date BETWEEN ? AND ?
               ORDER BY event_date, created_at""",
            (restaurant_id, start_date, end_date),
        )
        return c.fetchall()


def get_tips_summary(restaurant_id: int, start_date: str, end_date: str) -> dict:
    """Aggregate tip totals for a period, split by type (card/cash)."""
    events = get_tips_for_period(restaurant_id, start_date, end_date)
    totals = {"card": 0.0, "cash": 0.0, "unknown": 0.0, "events": len(events)}
    for t in events:
        tip_type = (t["tip_type"] or "unknown").lower()
        amount = t["gross_amount"] or 0.0
        if tip_type in totals:
            totals[tip_type] += amount
        else:
            totals["unknown"] += amount
    totals["total"] = round(totals["card"] + totals["cash"] + totals["unknown"], 2)
    totals["card"] = round(totals["card"], 2)
    totals["cash"] = round(totals["cash"], 2)
    totals["unknown"] = round(totals["unknown"], 2)
    return totals


# ── Allergen alerts ───────────────────────────────────────────────────────────

def save_allergen_alert(restaurant_id: int, entry_id: int, alert_date: str,
                        supplier_name: str, product_name: str, allergen_concern: str):
    """Record a Natasha's Law allergen traceability alert."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO allergen_alerts
               (restaurant_id, entry_id, alert_date, supplier_name, product_name, allergen_concern)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (restaurant_id, entry_id, alert_date, supplier_name, product_name, allergen_concern),
        )
        conn.commit()
        return c.lastrowid


def get_allergen_alerts(restaurant_id: int, days_back: int = 90) -> list:
    """Return recent allergen alerts for a restaurant."""
    with _db() as conn:
        c = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        c.execute(
            """SELECT * FROM allergen_alerts
               WHERE restaurant_id = ? AND alert_date >= ?
               ORDER BY alert_date DESC""",
            (restaurant_id, cutoff),
        )
        return c.fetchall()


def resolve_allergen_alert(alert_id: int) -> bool:
    """Mark an allergen alert as reviewed and resolved."""
    with _db() as conn:
        c = conn.cursor()
        c.execute("UPDATE allergen_alerts SET resolved = 1 WHERE id = ?", (alert_id,))
        conn.commit()
        return c.rowcount > 0


# ── Data management ───────────────────────────────────────────────────────────

def clear_all_entries(restaurant_id: int):
    """Delete all entries, invoices, tips and allergen alerts for a restaurant.
    Keeps the restaurant registration and staff records intact."""
    with _db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM allergen_alerts WHERE restaurant_id = ?", (restaurant_id,))
        c.execute("DELETE FROM tips_log WHERE restaurant_id = ?", (restaurant_id,))
        c.execute("DELETE FROM invoices WHERE restaurant_id = ?", (restaurant_id,))
        c.execute("DELETE FROM daily_entries WHERE restaurant_id = ?", (restaurant_id,))
        c.execute("DELETE FROM weekly_reports WHERE restaurant_id = ?", (restaurant_id,))
        conn.commit()


# ── Support tickets ───────────────────────────────────────────────────────────

def save_support_ticket(restaurant_id: int, chat_id: str, message: str) -> int:
    """Create a new support ticket from a restaurant."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT INTO support_tickets (restaurant_id, chat_id, message) VALUES (?, ?, ?)",
            (restaurant_id, chat_id, message),
        )
        conn.commit()
        return c.lastrowid


def get_support_tickets(restaurant_id: int) -> list:
    """Return all support tickets for a restaurant, newest first."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM support_tickets WHERE restaurant_id = ? ORDER BY created_at DESC",
            (restaurant_id,),
        )
        return c.fetchall()


def get_ticket_by_id(ticket_id: int):
    """Return a single ticket by ID."""
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,))
        return c.fetchone()


def resolve_support_ticket(ticket_id: int, reply_text: str):
    """Mark a ticket as resolved and store the owner's reply."""
    with _db() as conn:
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        c.execute(
            "UPDATE support_tickets SET status = 'resolved', owner_reply = ?, resolved_at = ? WHERE id = ?",
            (reply_text, now, ticket_id),
        )
        conn.commit()
        return c.rowcount > 0


def get_all_open_tickets() -> list:
    """Return all open tickets across all restaurants (for owner use)."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT t.*, r.name as restaurant_name
               FROM support_tickets t
               JOIN restaurants r ON t.restaurant_id = r.id
               WHERE t.status = 'open'
               ORDER BY t.created_at ASC""",
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

    # Include labour costs in the P&L
    labour = get_labour_for_period(restaurant_id, start_date, end_date)
    labour_total = sum(l["amount"] for l in labour)

    gross_profit = revenue_total - cost_total - labour_total
    net_margin = round(gross_profit / revenue_total * 100, 1) if revenue_total else 0.0
    # GP before labour (food cost margin, classic restaurant metric)
    food_gp = revenue_total - cost_total
    food_margin = round(food_gp / revenue_total * 100, 1) if revenue_total else 0.0

    return {
        "period_start": start_date,
        "period_end": end_date,
        "revenue_total": round(revenue_total, 2),
        "cost_total": round(cost_total, 2),
        "labour_total": round(labour_total, 2),
        "gross_profit": round(gross_profit, 2),
        "food_margin_pct": food_margin,
        "net_margin_pct": net_margin,
        "cost_items": cost_items,
        "labour_items": [{"date": l["labour_date"], "description": l["description"] or "Labour", "amount": l["amount"]} for l in labour],
    }


# ── Labour cost tracking ──────────────────────────────────────────────────────

def save_labour_entry(restaurant_id: int, labour_date: str, amount: float,
                      description: str, shift: str = None, hours: float = None,
                      entry_id: int = None) -> int:
    """Record a labour cost (wages, agency, contractor). Called by /labour command."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO labour_entries
               (restaurant_id, entry_id, labour_date, shift, amount, hours, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (restaurant_id, entry_id, labour_date, shift, amount, hours, description),
        )
        conn.commit()
        return c.lastrowid


def get_labour_for_period(restaurant_id: int, start_date: str, end_date: str) -> list:
    """Return all labour entries in a date range, newest first."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT * FROM labour_entries
               WHERE restaurant_id = ? AND labour_date BETWEEN ? AND ?
               ORDER BY labour_date DESC""",
            (restaurant_id, start_date, end_date),
        )
        return c.fetchall()


def get_labour_summary(restaurant_id: int, start_date: str, end_date: str) -> dict:
    """Total labour spend and breakdown for a period."""
    entries = get_labour_for_period(restaurant_id, start_date, end_date)
    total = sum(e["amount"] for e in entries)
    return {
        "total": round(total, 2),
        "entries": len(entries),
        "items": [dict(e) for e in entries],
    }


# ── Supplier price trend tracking ─────────────────────────────────────────────

def save_invoice_line_items(restaurant_id: int, invoice_id: int,
                             supplier_name: str, items: list, recorded_date: str):
    """
    Save line items from an invoice for price trend tracking.
    items: list of dicts with keys: name, unit_price, quantity, unit
    """
    with _db() as conn:
        c = conn.cursor()
        for item in items:
            item_name = (item.get("name") or "").strip()
            if not item_name:
                continue
            c.execute(
                """INSERT INTO invoice_line_items
                   (restaurant_id, invoice_id, supplier_name, item_name,
                    unit_price, quantity, unit, recorded_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    restaurant_id, invoice_id, supplier_name, item_name,
                    item.get("unit_price"), item.get("quantity"),
                    item.get("unit"), recorded_date,
                ),
            )
        conn.commit()


def get_price_history(restaurant_id: int, supplier_name: str,
                      item_name: str, limit: int = 5) -> list:
    """Return the last N unit prices for a given supplier+item combination."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT unit_price, recorded_date FROM invoice_line_items
               WHERE restaurant_id = ? AND supplier_name = ? AND item_name = ?
                 AND unit_price IS NOT NULL
               ORDER BY recorded_date DESC LIMIT ?""",
            (restaurant_id, supplier_name, item_name, limit),
        )
        return c.fetchall()


def detect_price_changes(restaurant_id: int, supplier_name: str,
                         items: list, recorded_date: str) -> list:
    """
    Compare new invoice line items against historical prices.
    Returns a list of dicts describing price changes above a 5% threshold.
    """
    alerts = []
    for item in items:
        item_name = (item.get("name") or "").strip()
        new_price = item.get("unit_price")
        if not item_name or not new_price:
            continue
        history = get_price_history(restaurant_id, supplier_name, item_name, limit=5)
        if not history:
            continue  # First time seeing this item — no baseline
        avg_price = sum(row["unit_price"] for row in history) / len(history)
        if avg_price <= 0:
            continue
        pct_change = (new_price - avg_price) / avg_price * 100
        if pct_change >= 5:
            alerts.append({
                "item": item_name,
                "supplier": supplier_name,
                "old_avg": round(avg_price, 2),
                "new_price": round(new_price, 2),
                "pct_change": round(pct_change, 1),
            })
        elif pct_change <= -5:
            alerts.append({
                "item": item_name,
                "supplier": supplier_name,
                "old_avg": round(avg_price, 2),
                "new_price": round(new_price, 2),
                "pct_change": round(pct_change, 1),
            })
    return alerts


# ── Multi-restaurant support ──────────────────────────────────────────────────

def get_all_restaurants() -> list:
    """Return all registered restaurants. Used by the scheduled report job."""
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM restaurants ORDER BY id")
        return c.fetchall()


# ── Weekly report history ─────────────────────────────────────────────────────

def get_weekly_reports(restaurant_id: int, limit: int = 4) -> list:
    """Return the most recent weekly reports for a restaurant."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT * FROM weekly_reports
               WHERE restaurant_id = ?
               ORDER BY week_start DESC LIMIT ?""",
            (restaurant_id, limit),
        )
        return c.fetchall()


def get_report_by_week(restaurant_id: int, week_start: str):
    """Return the saved report for a specific week start date (YYYY-MM-DD)."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM weekly_reports WHERE restaurant_id = ? AND week_start = ?",
            (restaurant_id, week_start),
        )
        return c.fetchone()


# ── Staff engagement / team stats ─────────────────────────────────────────────

def get_staff_entry_counts(restaurant_id: int, start_date: str, end_date: str) -> list:
    """
    Return entry counts per staff member for a period.
    Used by /teamstats.
    """
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT s.name, s.role, COUNT(e.id) as entry_count,
                      MAX(e.entry_date) as last_entry_date
               FROM staff s
               LEFT JOIN daily_entries e
                 ON e.staff_id = s.id
                 AND e.restaurant_id = s.restaurant_id
                 AND e.entry_date BETWEEN ? AND ?
               WHERE s.restaurant_id = ?
               GROUP BY s.id
               ORDER BY entry_count DESC""",
            (start_date, end_date, restaurant_id),
        )
        return c.fetchall()


# ── 86'd item trend tracking ──────────────────────────────────────────────────

def get_eightysix_trends(restaurant_id: int, start_date: str, end_date: str) -> list:
    """
    Aggregate all items_86d mentions across entries in a period.
    Returns list of (item_name, count) sorted by most frequent.
    """
    entries = get_entries_for_period(restaurant_id, start_date, end_date)
    counts: dict = {}
    for e in entries:
        if not e["structured_data"]:
            continue
        try:
            data = json.loads(e["structured_data"])
            for item in (data.get("items_86d") or []):
                if isinstance(item, str):
                    key = item.strip().lower()
                    if key:
                        counts[key] = counts.get(key, 0) + 1
        except (json.JSONDecodeError, TypeError):
            continue
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)


# ── GDPR data retention ───────────────────────────────────────────────────────

def delete_entries_older_than(restaurant_id: int, days: int) -> int:
    """
    Delete daily entries (and linked compliance records) older than `days` days.
    Returns the number of entries deleted.
    GDPR obligation: personal data should not be kept longer than necessary.
    """
    with _db() as conn:
        c = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # Find entry IDs to delete
        c.execute(
            "SELECT id FROM daily_entries WHERE restaurant_id = ? AND entry_date < ?",
            (restaurant_id, cutoff),
        )
        entry_ids = [row["id"] for row in c.fetchall()]

        if not entry_ids:
            return 0

        placeholders = ",".join("?" * len(entry_ids))
        c.execute(f"DELETE FROM tips_log WHERE entry_id IN ({placeholders})", entry_ids)
        c.execute(f"DELETE FROM allergen_alerts WHERE entry_id IN ({placeholders})", entry_ids)
        c.execute(f"DELETE FROM labour_entries WHERE entry_id IN ({placeholders})", entry_ids)
        c.execute(f"DELETE FROM daily_entries WHERE id IN ({placeholders})", entry_ids)
        conn.commit()
        return len(entry_ids)


# ── Stock par level tracking ──────────────────────────────────────────────────

def set_stock_par(restaurant_id: int, item_name: str, par_level: float, unit: str = "") -> int:
    """Create or update a stock par level for an item. Returns the row id."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO stock_items (restaurant_id, item_name, par_level, unit)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(restaurant_id, item_name)
               DO UPDATE SET par_level = excluded.par_level,
                             unit = CASE WHEN excluded.unit != '' THEN excluded.unit
                                         ELSE unit END""",
            (restaurant_id, item_name.lower().strip(), par_level, unit),
        )
        conn.commit()
        return c.lastrowid


def update_stock_count(restaurant_id: int, item_name: str, current_level: float) -> bool:
    """Record a stock count for an item. Item must already have a par level set.
    Returns True if updated, False if item not found."""
    with _db() as conn:
        c = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute(
            """UPDATE stock_items
               SET current_level = ?, last_count_date = ?
               WHERE restaurant_id = ? AND item_name = ?""",
            (current_level, today, restaurant_id, item_name.lower().strip()),
        )
        conn.commit()
        return c.rowcount > 0


def get_stock_status(restaurant_id: int) -> list:
    """Return all stock items for a restaurant, ordered by name."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT * FROM stock_items
               WHERE restaurant_id = ?
               ORDER BY item_name ASC""",
            (restaurant_id,),
        )
        return c.fetchall()


def get_low_stock_items(restaurant_id: int) -> list:
    """Return items where current_level < par_level (and current_level has been set)."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT * FROM stock_items
               WHERE restaurant_id = ?
                 AND current_level IS NOT NULL
                 AND current_level < par_level
               ORDER BY (par_level - current_level) DESC""",
            (restaurant_id,),
        )
        return c.fetchall()


def delete_stock_item(restaurant_id: int, item_name: str) -> bool:
    """Remove a stock item and its par level. Returns True if deleted."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "DELETE FROM stock_items WHERE restaurant_id = ? AND item_name = ?",
            (restaurant_id, item_name.lower().strip()),
        )
        conn.commit()
        return c.rowcount > 0


# ── Staff rota / shift scheduling ─────────────────────────────────────────────

def _ensure_rota_table(conn):
    """Create rota_shifts table if it doesn't exist yet (lazy migration)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rota_shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            restaurant_id INTEGER NOT NULL,
            shift_date TEXT NOT NULL,
            staff_name TEXT NOT NULL,
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            role TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
        )
    """)


def add_rota_shift(restaurant_id: int, shift_date: str, staff_name: str,
                   start_time: str = "", end_time: str = "",
                   role: str = "", notes: str = "") -> int:
    """Add a single shift to the rota. Returns the new row id."""
    with _db() as conn:
        _ensure_rota_table(conn)
        c = conn.cursor()
        c.execute(
            """INSERT INTO rota_shifts
               (restaurant_id, shift_date, staff_name, start_time, end_time, role, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (restaurant_id, shift_date, staff_name.strip(),
             start_time, end_time, role, notes),
        )
        conn.commit()
        return c.lastrowid


def get_rota_for_week(restaurant_id: int, week_start: str, week_end: str) -> list:
    """Return all shifts for a week, ordered by date then start_time."""
    with _db() as conn:
        _ensure_rota_table(conn)
        c = conn.cursor()
        c.execute(
            """SELECT * FROM rota_shifts
               WHERE restaurant_id = ? AND shift_date BETWEEN ? AND ?
               ORDER BY shift_date ASC, start_time ASC, staff_name ASC""",
            (restaurant_id, week_start, week_end),
        )
        return c.fetchall()


def delete_rota_shift(shift_id: int, restaurant_id: int) -> bool:
    """Delete a shift by id. Requires restaurant_id for safety. Returns True if deleted."""
    with _db() as conn:
        _ensure_rota_table(conn)
        c = conn.cursor()
        c.execute(
            "DELETE FROM rota_shifts WHERE id = ? AND restaurant_id = ?",
            (shift_id, restaurant_id),
        )
        conn.commit()
        return c.rowcount > 0


def copy_rota_week(restaurant_id: int, from_start: str, from_end: str,
                   to_start: str) -> int:
    """Copy all shifts from one week to a target week.
    to_start is the Monday of the destination week.
    Returns count of shifts copied."""
    source_shifts = get_rota_for_week(restaurant_id, from_start, from_end)
    if not source_shifts:
        return 0
    from datetime import datetime as _dt, timedelta as _td
    from_monday = _dt.strptime(from_start, "%Y-%m-%d").date()
    to_monday = _dt.strptime(to_start, "%Y-%m-%d").date()
    offset = to_monday - from_monday
    copied = 0
    with _db() as conn:
        _ensure_rota_table(conn)
        c = conn.cursor()
        for shift in source_shifts:
            original = _dt.strptime(shift["shift_date"], "%Y-%m-%d").date()
            new_date = (original + offset).strftime("%Y-%m-%d")
            c.execute(
                """INSERT INTO rota_shifts
                   (restaurant_id, shift_date, staff_name, start_time, end_time, role, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (restaurant_id, new_date, shift["staff_name"],
                 shift["start_time"], shift["end_time"],
                 shift["role"], shift["notes"]),
            )
            copied += 1
        conn.commit()
    return copied


def clear_rota_week(restaurant_id: int, week_start: str, week_end: str) -> int:
    """Delete all shifts for a week. Returns count deleted."""
    with _db() as conn:
        _ensure_rota_table(conn)
        c = conn.cursor()
        c.execute(
            "DELETE FROM rota_shifts WHERE restaurant_id = ? AND shift_date BETWEEN ? AND ?",
            (restaurant_id, week_start, week_end),
        )
        conn.commit()
        return c.rowcount


# ── Dashboard token ────────────────────────────────────────────────────────────

def get_or_create_dashboard_token(restaurant_id: int) -> str:
    """Return the dashboard auth token for a restaurant, creating one if needed."""
    import uuid as _uuid
    with _db() as conn:
        try:
            conn.execute("ALTER TABLE restaurants ADD COLUMN dashboard_token TEXT")
            conn.commit()
        except Exception:
            pass  # column already exists
        c = conn.cursor()
        c.execute("SELECT dashboard_token FROM restaurants WHERE id = ?", (restaurant_id,))
        row = c.fetchone()
        if row and row["dashboard_token"]:
            return row["dashboard_token"]
        token = _uuid.uuid4().hex
        c.execute(
            "UPDATE restaurants SET dashboard_token = ? WHERE id = ?",
            (token, restaurant_id),
        )
        conn.commit()
        return token


def get_restaurant_by_dashboard_token(token: str):
    """Return the restaurant row matching a dashboard token, or None."""
    with _db() as conn:
        c = conn.cursor()
        try:
            c.execute("SELECT * FROM restaurants WHERE dashboard_token = ?", (token,))
            return c.fetchone()
        except Exception:
            return None
