"""
crm.py — Analyst CRM and human-in-the-loop workflow for Restaurant-IQ.

This module handles the human side of the Managed and Enterprise tiers:

  · Analyst assignment (each Managed/Enterprise client gets a named advisor)
  · Internal analyst notes (observations, actions, alerts per client)
  · Hours tracking (ensures each client gets their contracted weekly hours)
  · Human-in-the-loop weekly report workflow:
      1. Bot generates AI report
      2. Bot sends it to analyst's private Telegram with a review prompt
      3. Analyst adds commentary or approves within the review window
      4. Enriched report (AI + human insight) goes to the restaurant
  · Weekly client digest (sent to each analyst on Sunday evening)
  · Client health scoring (data volume, trend quality, response rates)

ANALYST COMMANDS (internal, only works from analyst Telegram IDs):
  /analyst clients              — list all my assigned clients
  /analyst review               — this week's data for a specific client
  /analyst note [id] [text]     — add internal note to a client
  /analyst hours [id] [h] [act] — log time spent on a client
  /analyst approve [id]         — approve AI report without changes
  /analyst addnote [id] [text]  — add commentary to a client's pending report
  /analyst assign [id]          — assign yourself to a client
  /analyst digest               — show all clients needing review this week
"""

from datetime import datetime, timedelta
from database import _db


# ─── Analyst DB helpers ───────────────────────────────────────────────────────

def get_analyst_by_telegram_id(telegram_id: str):
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM analysts WHERE telegram_id = ?", (str(telegram_id),))
        return c.fetchone()


def get_all_analysts() -> list:
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM analysts ORDER BY name")
        return c.fetchall()


def create_analyst(name: str, telegram_id: str, email: str = "") -> int:
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR IGNORE INTO analysts (name, telegram_id, email) VALUES (?, ?, ?)",
            (name, str(telegram_id), email),
        )
        conn.commit()
        c.execute("SELECT id FROM analysts WHERE telegram_id = ?", (str(telegram_id),))
        row = c.fetchone()
        return row["id"] if row else None


def assign_analyst(restaurant_id: int, analyst_id: int):
    """Assign an analyst to a restaurant (replaces any existing assignment)."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO restaurant_analysts (restaurant_id, analyst_id) VALUES (?, ?)",
            (restaurant_id, analyst_id),
        )
        conn.commit()


def get_analyst_for_restaurant(restaurant_id: int):
    """Return the analyst assigned to a restaurant, or None."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT a.* FROM analysts a
               JOIN restaurant_analysts ra ON ra.analyst_id = a.id
               WHERE ra.restaurant_id = ?""",
            (restaurant_id,),
        )
        return c.fetchone()


def get_clients_for_analyst(analyst_id: int) -> list:
    """Return all restaurants assigned to an analyst."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT r.* FROM restaurants r
               JOIN restaurant_analysts ra ON ra.restaurant_id = r.id
               WHERE ra.analyst_id = ?
               ORDER BY r.name""",
            (analyst_id,),
        )
        return c.fetchall()


# ─── Notes ────────────────────────────────────────────────────────────────────

def add_analyst_note(restaurant_id: int, analyst_id: int,
                     note_text: str, note_type: str = "observation"):
    """
    Add an internal note to a client file.
    note_type: observation | action | alert | call_note
    """
    with _db() as conn:
        conn.execute(
            """INSERT INTO analyst_notes
               (restaurant_id, analyst_id, note_text, note_type)
               VALUES (?, ?, ?, ?)""",
            (restaurant_id, analyst_id, note_text, note_type),
        )
        conn.commit()


def get_analyst_notes(restaurant_id: int, limit: int = 10) -> list:
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT n.*, a.name as analyst_name FROM analyst_notes n
               LEFT JOIN analysts a ON a.id = n.analyst_id
               WHERE n.restaurant_id = ?
               ORDER BY n.created_at DESC LIMIT ?""",
            (restaurant_id, limit),
        )
        return c.fetchall()


# ─── Hours tracking ───────────────────────────────────────────────────────────

def log_analyst_hours(restaurant_id: int, analyst_id: int,
                      hours: float, activity: str, week_start: str = None):
    if week_start is None:
        today = datetime.now()
        week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    with _db() as conn:
        conn.execute(
            """INSERT INTO analyst_hours_log
               (restaurant_id, analyst_id, hours_spent, activity, week_start)
               VALUES (?, ?, ?, ?, ?)""",
            (restaurant_id, analyst_id, hours, activity, week_start),
        )
        conn.commit()


def get_hours_this_week(restaurant_id: int, analyst_id: int) -> float:
    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT COALESCE(SUM(hours_spent), 0) as total
               FROM analyst_hours_log
               WHERE restaurant_id = ? AND analyst_id = ? AND week_start = ?""",
            (restaurant_id, analyst_id, week_start),
        )
        row = c.fetchone()
        return float(row["total"]) if row else 0.0


def get_hours_summary_for_analyst(analyst_id: int) -> list:
    """Return hours spent per client this week."""
    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT r.name, r.id, COALESCE(SUM(h.hours_spent), 0) as hours
               FROM restaurants r
               JOIN restaurant_analysts ra ON ra.restaurant_id = r.id
               LEFT JOIN analyst_hours_log h
                   ON h.restaurant_id = r.id AND h.analyst_id = ? AND h.week_start = ?
               WHERE ra.analyst_id = ?
               GROUP BY r.id
               ORDER BY r.name""",
            (analyst_id, week_start, analyst_id),
        )
        return c.fetchall()


# ─── Human-in-the-loop report workflow ───────────────────────────────────────

def create_pending_report(restaurant_id: int, report_text: str,
                           pdf_path: str, week_start: str) -> int:
    """
    Create a pending report waiting for analyst review.
    Returns the pending_report id.
    """
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """INSERT INTO pending_reports
               (restaurant_id, ai_report_text, pdf_path, week_start, status)
               VALUES (?, ?, ?, ?, 'awaiting_review')""",
            (restaurant_id, report_text, pdf_path, week_start),
        )
        conn.commit()
        return c.lastrowid


def get_pending_report(pending_id: int):
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM pending_reports WHERE id = ?", (pending_id,))
        return c.fetchone()


def get_pending_reports_for_analyst(analyst_id: int) -> list:
    """All reports awaiting this analyst's review."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT pr.*, r.name as restaurant_name, r.telegram_group_id
               FROM pending_reports pr
               JOIN restaurants r ON r.id = pr.restaurant_id
               JOIN restaurant_analysts ra ON ra.restaurant_id = r.id
               WHERE ra.analyst_id = ? AND pr.status = 'awaiting_review'
               ORDER BY pr.created_at""",
            (analyst_id,),
        )
        return c.fetchall()


def approve_report(pending_id: int, analyst_note: str = "") -> dict:
    """
    Analyst approves the AI report (optionally with added commentary).
    Returns the pending_report row.
    """
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """UPDATE pending_reports
               SET status = 'approved', analyst_note = ?, reviewed_at = ?
               WHERE id = ?""",
            (analyst_note, datetime.now().isoformat(), pending_id),
        )
        conn.commit()
        c.execute("SELECT * FROM pending_reports WHERE id = ?", (pending_id,))
        return c.fetchone()


def set_pending_report_note(pending_id: int, note: str):
    """Save or update an analyst's note on a pending report without approving it."""
    with _db() as conn:
        conn.execute("UPDATE pending_reports SET analyst_note = ? WHERE id = ?",
                     (note, pending_id))
        conn.commit()


def get_pending_report_by_restaurant(restaurant_id: int):
    """Most recent pending report for a restaurant."""
    with _db() as conn:
        c = conn.cursor()
        c.execute(
            """SELECT * FROM pending_reports
               WHERE restaurant_id = ? AND status = 'awaiting_review'
               ORDER BY created_at DESC LIMIT 1""",
            (restaurant_id,),
        )
        return c.fetchone()


# ─── Client health score ──────────────────────────────────────────────────────

def client_health_score(restaurant_id: int, entries_this_week: int,
                         entries_last_week: int) -> dict:
    """
    Simple health score for the analyst dashboard.
    Returns: {score: 0-100, label: str, flags: list}
    """
    score  = 50
    flags  = []

    # Entry volume
    if entries_this_week >= 15:
        score += 25
    elif entries_this_week >= 8:
        score += 15
    elif entries_this_week >= 3:
        score += 5
    else:
        score -= 15
        flags.append("Very low data volume this week")

    # Week-on-week consistency
    if entries_last_week > 0:
        ratio = entries_this_week / entries_last_week
        if ratio >= 0.8:
            score += 15
        elif ratio < 0.4:
            score -= 10
            flags.append("Entry volume dropped >60% vs last week")

    score = max(0, min(100, score))

    if score >= 75:
        label = "Healthy 🟢"
    elif score >= 50:
        label = "Moderate 🟡"
    else:
        label = "Needs attention 🔴"

    return {"score": score, "label": label, "flags": flags}


# ─── Formatting helpers ────────────────────────────────────────────────────────

def format_analyst_digest(analyst_id: int, clients: list,
                           pending_reports: list) -> str:
    """
    Weekly digest message sent to an analyst.
    Summarises all their clients: health, hours used, pending reports.
    """
    if not clients:
        return "No clients assigned to you yet."

    pending_ids = {pr["restaurant_id"] for pr in pending_reports}
    lines = ["YOUR CLIENT DIGEST\n" + "─" * 34, ""]

    for c in clients:
        needs_review = "⚠️ REVIEW NEEDED" if c["id"] in pending_ids else "✅ up to date"
        tier = c.get("subscription_tier") or "solo"
        lines.append(f"  {c['name']}  [{tier.upper()}]  {needs_review}")

    lines += ["", f"Pending reports to review: {len(pending_reports)}"]
    if pending_reports:
        for pr in pending_reports:
            lines.append(
                f"  → {pr['restaurant_name']} (week of {pr['week_start']}) "
                "— /analyst addnote or /analyst approve"
            )

    return "\n".join(lines)


def format_analyst_note_for_report(analyst_note: str, analyst_name: str) -> str:
    """
    Format the analyst's commentary for appending to the weekly report.
    This is the human touch that appears after the AI-generated content.
    """
    if not analyst_note or not analyst_note.strip():
        return ""
    return (
        "\n\n---\n"
        f"## YOUR ADVISOR'S NOTE — {analyst_name.upper()}\n\n"
        f"{analyst_note.strip()}\n\n"
        f"*{analyst_name}, Restaurant-IQ*  \n"
        f"*For queries, reply to this message or book a call via your Flivio dashboard.*"
    )
