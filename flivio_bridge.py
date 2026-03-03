"""
flivio_bridge.py — Integration layer between Restaurant-IQ Bot and Flivio.

Flivio is a companion web app (React + Express + PostgreSQL) that provides
visual dashboards, recipe costing, delivery platform analysis, and
what-if scenario modelling.

Together they form a complete restaurant intelligence stack:
  ┌─────────────────────────────────────────────────────────┐
  │  STAFF         → Telegram group (voice, photos, texts)  │
  │  BOT           → Captures, transcribes, analyses        │
  │  FLIVIO        → Visual dashboards, drill-down, recipes │
  │  ANALYST       → Human review layer (Managed/Enterprise)│
  │  OWNER         → Weekly briefing + PDF + personal note  │
  └─────────────────────────────────────────────────────────┘

INTEGRATION APPROACHES (in order of setup complexity):

1. CSV EXPORT (works today, zero additional setup)
   Bot's /export command generates a CSV matching Flivio's bulk import format.
   Owner uploads to Flivio → instant dashboard population.

2. REST API PUSH (recommended for Managed/Enterprise clients)
   When FLIVIO_API_URL and FLIVIO_API_KEY are set in .env, the bot
   automatically pushes daily entry summaries to Flivio after each save.

3. SHARED DATABASE (for operators running both on same infrastructure)
   Point both apps at the same PostgreSQL instance.
   Set FLIVIO_SHARED_DB=true and DB_PATH to the PostgreSQL connection string.

4. WEBHOOK FROM FLIVIO TO BOT (future)
   Flivio can POST alerts to the bot when KPI thresholds are breached.
   e.g. "Food cost budget exceeded" → bot sends instant Telegram alert.
"""

import csv
import io
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from config import FLIVIO_API_URL, FLIVIO_API_KEY
except ImportError:
    FLIVIO_API_URL = None
    FLIVIO_API_KEY = None


# ─── Approach 1: CSV Export (Flivio bulk import format) ──────────────────────

def export_entries_to_flivio_csv(entries: list, restaurant_name: str,
                                  week_start: str) -> bytes:
    """
    Export bot entries as a CSV in Flivio's bulk import format.
    Matches Flivio's expected columns for monthly financial data import.

    Flivio expects: date, category, description, amount, type (income/expense)
    Returns bytes ready to send as a file attachment.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Flivio bulk import format (matches Flivio's /api/bulk-import endpoint)
    writer.writerow([
        "date", "category", "description", "amount", "type",
        "supplier", "urgency", "source", "raw_text"
    ])

    for e in entries:
        a = {}
        if e.get("structured_data"):
            try:
                a = json.loads(e["structured_data"]) if isinstance(e["structured_data"], str) else e["structured_data"]
            except (json.JSONDecodeError, TypeError):
                pass

        category = e.get("category") or a.get("category", "general")
        amount = None
        entry_type = "expense"

        if category == "revenue":
            amount = a.get("revenue")
            entry_type = "income"
        elif category == "cost":
            amount = a.get("total_amount")
            entry_type = "expense"
        elif category == "waste":
            amount = a.get("waste_cost")
            entry_type = "expense"

        writer.writerow([
            e.get("entry_date", week_start),
            category,
            a.get("summary", e.get("raw_text", "")[:80]),
            amount or "",
            entry_type,
            a.get("supplier_name", ""),
            a.get("urgency", ""),
            f"Restaurant-IQ Bot ({e.get('entry_type', 'text')})",
            (e.get("raw_text") or "")[:200],
        ])

    return buf.getvalue().encode("utf-8")


def export_suppliers_to_flivio_csv(supplier_prices: dict) -> bytes:
    """
    Export supplier price data in Flivio's supplier import format.
    supplier_prices: {supplier_name: {item_name: {"unit_price": float, "unit": str}}}
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["supplier_name", "item_name", "unit_price", "unit", "recorded_date"])

    today = datetime.now().strftime("%Y-%m-%d")
    for supplier, items in supplier_prices.items():
        for item, data in items.items():
            writer.writerow([
                supplier, item,
                data.get("unit_price", ""),
                data.get("unit", ""),
                today,
            ])

    return buf.getvalue().encode("utf-8")


# ─── Approach 2: REST API Push ────────────────────────────────────────────────

def push_entry_to_flivio(entry_data: dict, restaurant_flivio_id: str) -> bool:
    """
    Push a single entry to Flivio's REST API.
    Called after save_entry() for Managed/Enterprise clients.
    Returns True on success.

    Requires FLIVIO_API_URL and FLIVIO_API_KEY in .env.
    Flivio endpoint: POST /api/restaurants/{id}/entries
    """
    if not FLIVIO_API_URL or not FLIVIO_API_KEY:
        return False  # Not configured — skip silently
    if not restaurant_flivio_id:
        return False

    try:
        import urllib.request
        payload = json.dumps(entry_data).encode("utf-8")
        req = urllib.request.Request(
            f"{FLIVIO_API_URL.rstrip('/')}/api/restaurants/{restaurant_flivio_id}/entries",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {FLIVIO_API_KEY}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning(f"Flivio API push failed: {e}")
        return False


def push_weekly_summary_to_flivio(kpis: dict, restaurant_flivio_id: str,
                                   week_start: str) -> bool:
    """
    Push the weekly KPI summary to Flivio for dashboard display.
    Flivio endpoint: POST /api/restaurants/{id}/monthly-data
    """
    if not FLIVIO_API_URL or not FLIVIO_API_KEY or not restaurant_flivio_id:
        return False

    payload_data = {
        "period":          week_start,
        "revenue":         kpis.get("revenue", 0),
        "food_cost":       kpis.get("food_cost", 0),
        "food_cost_pct":   kpis.get("food_cost_pct"),
        "gp_pct":          kpis.get("gp_pct"),
        "covers":          kpis.get("covers", 0),
        "waste_cost":      kpis.get("waste_cost", 0),
        "entry_count":     kpis.get("entry_count", 0),
        "source":          "restaurant-iq-bot",
    }

    try:
        import urllib.request
        payload = json.dumps(payload_data).encode("utf-8")
        req = urllib.request.Request(
            f"{FLIVIO_API_URL.rstrip('/')}/api/restaurants/{restaurant_flivio_id}/monthly-data",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {FLIVIO_API_KEY}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 201)
    except Exception as e:
        logger.warning(f"Flivio weekly summary push failed: {e}")
        return False


# ─── Integration status message ───────────────────────────────────────────────

def get_integration_status() -> str:
    """Return a human-readable status of the Flivio integration."""
    if FLIVIO_API_URL and FLIVIO_API_KEY:
        return f"✅ Flivio API connected ({FLIVIO_API_URL})"
    return (
        "Flivio integration: CSV export only (set FLIVIO_API_URL + FLIVIO_API_KEY "
        "in .env for live data push)"
    )


def get_flivio_dashboard_url(restaurant_flivio_id: str = None) -> str:
    """Return the Flivio dashboard URL for a restaurant."""
    base = (FLIVIO_API_URL or "").replace("/api", "").rstrip("/")
    if not base:
        return "https://your-flivio-instance.com"
    if restaurant_flivio_id:
        return f"{base}/dashboard/{restaurant_flivio_id}"
    return f"{base}/dashboard"
