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
    now = datetime.now()
    start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    return get_entries_for_period(restaurant_id, start, end)


def save_weekly_report(restaurant_id: int, week_start: str, week_end: str, report_text: str):
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO weekly_reports (restaurant_id, week_start, week_end, report_text)
               VALUES (?, ?, ?, ?)""",
            (restaurant_id, week_start, week_end, report_text),
        )
        conn.commit()
