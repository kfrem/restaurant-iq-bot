"""
database.py — SQLite data layer for Restaurant-IQ.

All DB access goes through this module. Never call sqlite3 directly from bot.py.

Schema:
  restaurants     — one row per registered Telegram group
  staff           — auto-registered members
  daily_entries   — every message captured (voice/photo/text)
  weekly_reports  — archived weekly briefings
  supplier_prices — per-item price history for supplier intelligence
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from config import DB_PATH


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # better concurrent reads
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with _db() as conn:
        c = conn.cursor()

        # ── Core tables ───────────────────────────────────────────────────────
        c.execute("""
            CREATE TABLE IF NOT EXISTS restaurants (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                name                 TEXT NOT NULL,
                telegram_group_id    TEXT UNIQUE,
                owner_telegram_id    TEXT,
                subscription_status  TEXT DEFAULT 'trial',
                subscription_tier    TEXT,
                stripe_customer_id   TEXT,
                target_food_cost_pct REAL DEFAULT 30.0,
                target_gp_pct        REAL DEFAULT 70.0,
                restaurant_type      TEXT DEFAULT 'casual',
                created_at           TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS staff (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id    INTEGER,
                telegram_user_id TEXT,
                name             TEXT,
                role             TEXT DEFAULT 'staff',
                UNIQUE(restaurant_id, telegram_user_id),
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_entries (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id   INTEGER NOT NULL,
                staff_id        INTEGER,
                entry_date      TEXT NOT NULL,
                entry_time      TEXT NOT NULL,
                entry_type      TEXT NOT NULL,
                raw_text        TEXT,
                structured_data TEXT,
                category        TEXT DEFAULT 'general',
                created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id),
                FOREIGN KEY (staff_id)      REFERENCES staff(id)
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_entries_restaurant_date
            ON daily_entries (restaurant_id, entry_date)
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS weekly_reports (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER NOT NULL,
                week_start    TEXT NOT NULL,
                week_end      TEXT NOT NULL,
                report_text   TEXT,
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS supplier_prices (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER NOT NULL,
                supplier_name TEXT NOT NULL,
                item_name     TEXT NOT NULL,
                unit_price    REAL,
                unit          TEXT,
                recorded_date TEXT NOT NULL,
                created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id)
            )
        """)
        c.execute("""
            CREATE INDEX IF NOT EXISTS idx_supplier_prices_restaurant
            ON supplier_prices (restaurant_id, supplier_name, recorded_date)
        """)

        # ── Migrations: add new columns to existing DBs safely ────────────────
        _add_column_if_missing(c, "restaurants", "subscription_status",  "TEXT DEFAULT 'trial'")
        _add_column_if_missing(c, "restaurants", "subscription_tier",    "TEXT")
        _add_column_if_missing(c, "restaurants", "stripe_customer_id",   "TEXT")
        _add_column_if_missing(c, "restaurants", "target_food_cost_pct", "REAL DEFAULT 30.0")
        _add_column_if_missing(c, "restaurants", "target_gp_pct",        "REAL DEFAULT 70.0")
        _add_column_if_missing(c, "restaurants", "restaurant_type",      "TEXT DEFAULT 'casual'")

        conn.commit()

    print("Database initialised.")


def _add_column_if_missing(cursor, table: str, column: str, col_def: str):
    """Add a column to an existing table if it doesn't already exist."""
    try:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
    except sqlite3.OperationalError:
        pass  # Column already exists


# ── Restaurant CRUD ───────────────────────────────────────────────────────────

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


def get_restaurant_by_group(group_id: str):
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM restaurants WHERE telegram_group_id = ?", (str(group_id),))
        return c.fetchone()


def get_all_restaurants() -> list:
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM restaurants ORDER BY id")
        return c.fetchall()


def update_restaurant_targets(restaurant_id: int, food_cost_pct: float = None,
                               gp_pct: float = None, restaurant_type: str = None):
    fields, values = [], []
    if food_cost_pct is not None:
        fields.append("target_food_cost_pct = ?")
        values.append(food_cost_pct)
    if gp_pct is not None:
        fields.append("target_gp_pct = ?")
        values.append(gp_pct)
    if restaurant_type is not None:
        fields.append("restaurant_type = ?")
        values.append(restaurant_type)
    if not fields:
        return
    values.append(restaurant_id)
    with _db() as conn:
        conn.execute(f"UPDATE restaurants SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()


def update_subscription(restaurant_id: int, status: str,
                         tier: str = None, stripe_customer_id: str = None):
    """Update subscription status after a Stripe webhook event."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE restaurants SET subscription_status=?, subscription_tier=?, stripe_customer_id=? WHERE id=?",
            (status, tier, stripe_customer_id, restaurant_id),
        )
        conn.commit()


# ── Staff ─────────────────────────────────────────────────────────────────────

def register_staff(restaurant_id: int, telegram_user_id: str, name: str, role: str = "staff"):
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO staff (restaurant_id, telegram_user_id, name, role) VALUES (?, ?, ?, ?)",
            (restaurant_id, str(telegram_user_id), name, role),
        )
        conn.commit()


def get_or_register_staff(restaurant_id: int, telegram_user_id: str, name: str, role: str = "staff"):
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


# ── Entries ───────────────────────────────────────────────────────────────────

def save_entry(restaurant_id: int, staff_id: int, entry_type: str,
               raw_text: str, structured_data: str, category: str):
    with _db() as conn:
        now = datetime.now()
        conn.execute(
            """INSERT INTO daily_entries
               (restaurant_id, staff_id, entry_date, entry_time, entry_type, raw_text, structured_data, category)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (restaurant_id, staff_id,
             now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"),
             entry_type, raw_text, structured_data, category),
        )
        conn.commit()


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


def get_week_entries(restaurant_id: int):
    now   = datetime.now()
    start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    end   = now.strftime("%Y-%m-%d")
    return get_entries_for_period(restaurant_id, start, end)


def get_prev_week_entries(restaurant_id: int):
    now        = datetime.now()
    this_start = now - timedelta(days=now.weekday())
    prev_start = this_start - timedelta(days=7)
    prev_end   = this_start - timedelta(days=1)
    return get_entries_for_period(
        restaurant_id,
        prev_start.strftime("%Y-%m-%d"),
        prev_end.strftime("%Y-%m-%d"),
    )


def delete_old_entries(restaurant_id: int, days: int = 90) -> int:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "DELETE FROM daily_entries WHERE restaurant_id = ? AND entry_date < ?",
            (restaurant_id, cutoff),
        )
        count = c.rowcount
        conn.commit()
    return count


def delete_all_entries(restaurant_id: int) -> int:
    with _db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM daily_entries WHERE restaurant_id = ?", (restaurant_id,))
        count = c.rowcount
        conn.commit()
    return count


# ── Weekly reports ────────────────────────────────────────────────────────────

def save_weekly_report(restaurant_id: int, week_start: str, week_end: str, report_text: str):
    with _db() as conn:
        conn.execute(
            "INSERT INTO weekly_reports (restaurant_id, week_start, week_end, report_text) VALUES (?, ?, ?, ?)",
            (restaurant_id, week_start, week_end, report_text),
        )
        conn.commit()


def get_weekly_reports(restaurant_id: int, limit: int = 4) -> list:
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM weekly_reports WHERE restaurant_id = ? ORDER BY week_start DESC LIMIT ?",
            (restaurant_id, limit),
        )
        return c.fetchall()


def get_report_by_week(restaurant_id: int, week_start: str):
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT * FROM weekly_reports WHERE restaurant_id = ? AND week_start = ? ORDER BY created_at DESC LIMIT 1",
            (restaurant_id, week_start),
        )
        return c.fetchone()


# ── Supplier price history ────────────────────────────────────────────────────

def save_supplier_prices(restaurant_id: int, prices: dict, recorded_date: str):
    """
    Save supplier prices extracted from invoices.
    prices: {supplier_name: {item_name: {"unit_price": float, "unit": str}}}
    """
    rows = []
    for supplier, items in prices.items():
        for item_name, data in items.items():
            rows.append((
                restaurant_id, supplier, item_name,
                data.get("unit_price"), data.get("unit", ""), recorded_date,
            ))
    if not rows:
        return
    with _db() as conn:
        conn.executemany(
            """INSERT INTO supplier_prices
               (restaurant_id, supplier_name, item_name, unit_price, unit, recorded_date)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()


def get_supplier_prices(restaurant_id: int, days_ago: int = 30) -> dict:
    """
    Return the most recent price for each supplier+item within the last N days.
    Returns: {supplier_name: {item_name: {"unit_price": float, "unit": str}}}
    """
    since = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    with _db() as conn:
        c = conn.cursor()
        # Get the latest price per supplier+item
        c.execute(
            """SELECT supplier_name, item_name, unit_price, unit
               FROM supplier_prices
               WHERE restaurant_id = ? AND recorded_date >= ?
               GROUP BY supplier_name, item_name
               HAVING recorded_date = MAX(recorded_date)""",
            (restaurant_id, since),
        )
        rows = c.fetchall()

    prices: dict = {}
    for row in rows:
        supplier  = row["supplier_name"]
        item      = row["item_name"]
        prices.setdefault(supplier, {})[item] = {
            "unit_price": row["unit_price"],
            "unit":       row["unit"] or "",
        }
    return prices


def get_historic_supplier_prices(restaurant_id: int,
                                  days_start: int = 60, days_end: int = 8) -> dict:
    """
    Return historic prices (between days_start and days_end days ago).
    Used as the baseline for price change detection.
    """
    date_start = (datetime.now() - timedelta(days=days_start)).strftime("%Y-%m-%d")
    date_end   = (datetime.now() - timedelta(days=days_end)).strftime("%Y-%m-%d")
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT supplier_name, item_name, unit_price, unit
               FROM supplier_prices
               WHERE restaurant_id = ? AND recorded_date BETWEEN ? AND ?
               GROUP BY supplier_name, item_name
               HAVING recorded_date = MAX(recorded_date)""",
            (restaurant_id, date_start, date_end),
        )
        rows = c.fetchall()

    prices: dict = {}
    for row in rows:
        supplier = row["supplier_name"]
        item     = row["item_name"]
        prices.setdefault(supplier, {})[item] = {
            "unit_price": row["unit_price"],
            "unit":       row["unit"] or "",
        }
    return prices
