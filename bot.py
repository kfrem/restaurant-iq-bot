"""
Restaurant-IQ Telegram Bot
--------------------------
Entry point. Run with:  python bot.py

Handles:
  - /start          — welcome message
  - /register       — register this Telegram group as a restaurant
  - /status         — show entries captured this week
  - /weeklyreport   — generate and send the weekly intelligence briefing
  - /recall [date]  — recall what was recorded on a specific date or period
  - /financials     — P&L and cashflow summary for any period
  - /outstanding    — list all unpaid invoices with due dates
  - /markpaid [id]  — mark an invoice as paid
  - /demo           — load a realistic week of demo data for client presentations
  - /demoreset      — remove all demo data from this chat

Message types:
  - Voice notes  → transcribed by Whisper → analysed by AI
  - Photos       → analysed by AI vision (invoice/receipt reading)
  - Text         → analysed by AI fast model
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta, date

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import TELEGRAM_BOT_TOKEN
from database import (
    init_db,
    register_restaurant,
    get_restaurant_by_group,
    register_staff,
    get_or_register_staff,
    save_entry,
    save_invoice,
    get_last_entry,
    update_entry,
    delete_last_entry,
    get_week_entries,
    get_entries_for_period,
    get_entries_with_staff,
    get_outstanding_invoices,
    get_invoices_due_soon,
    mark_invoice_paid,
    get_financial_summary,
    save_weekly_report,
    get_connection,
)
from transcriber import transcribe_audio
from analyzer import analyze_text_entry, analyze_invoice_photo, generate_weekly_report
from model_router import get_tier_status, generate_recall_summary
from report_generator import generate_pdf_report
from demo_data import get_demo_entries, DEMO_STAFF

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

REPORTS_DIR = "reports"
VOICE_DIR = "voice_files"
PHOTO_DIR = "photo_files"

URGENCY_ICONS = {"high": "🔴", "medium": "🟡", "low": "🟢"}

for _d in [REPORTS_DIR, VOICE_DIR, PHOTO_DIR]:
    os.makedirs(_d, exist_ok=True)


def _fmt_date(date_str: str | None) -> str:
    """Convert YYYY-MM-DD to British format: 6 March 2026. Returns original string on failure."""
    if not date_str:
        return "unknown"
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%-d %B %Y")
    except ValueError:
        return date_str


# ── Month name lookup for /recall date parsing ────────────────────────────────

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def _parse_date_range(text: str) -> tuple[str, str] | None:
    """
    Parse human-friendly date text into (start_date, end_date) as YYYY-MM-DD strings.
    Handles: today, yesterday, this week, last week, this month, last month,
             "25 march", "5th may", "5 may 2026", "march", "march 2026", "2026-03-25"
    Returns None if the text cannot be parsed.
    """
    text = text.strip().lower()
    today = date.today()

    if text == "today":
        return str(today), str(today)
    if text == "yesterday":
        d = today - timedelta(days=1)
        return str(d), str(d)
    if text in ("this week", "week"):
        start = today - timedelta(days=today.weekday())
        return str(start), str(today)
    if text == "last week":
        start = today - timedelta(days=today.weekday() + 7)
        end = today - timedelta(days=today.weekday() + 1)
        return str(start), str(end)
    if text in ("this month", "month"):
        return str(today.replace(day=1)), str(today)
    if text == "last month":
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return str(last_prev.replace(day=1)), str(last_prev)

    # "25 march", "5th may", "25th march 2026", "25 march 2026"
    m = re.match(r"(\d{1,2})(?:st|nd|rd|th)?\s+(\w+)(?:\s+(\d{4}))?$", text)
    if m:
        day = int(m.group(1))
        month = _MONTHS.get(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if month:
            try:
                d = date(year, month, day)
                return str(d), str(d)
            except ValueError:
                pass

    # "march 2026" or just "march" → whole month
    m = re.match(r"(\w+)(?:\s+(\d{4}))?$", text)
    if m:
        month = _MONTHS.get(m.group(1))
        if month:
            year = int(m.group(2)) if m.group(2) else today.year
            first = date(year, month, 1)
            last = (date(year, month + 1, 1) - timedelta(days=1)) if month < 12 else date(year, 12, 31)
            return str(first), str(last)

    # ISO format "2026-03-25"
    try:
        d = datetime.strptime(text, "%Y-%m-%d").date()
        return str(d), str(d)
    except ValueError:
        pass

    # Just a day number "25" → 25th of current month
    if text.isdigit():
        day = int(text)
        if 1 <= day <= 31:
            try:
                d = today.replace(day=day)
                if d > today:
                    prev = today.replace(day=1) - timedelta(days=1)
                    d = prev.replace(day=day)
                return str(d), str(d)
            except ValueError:
                pass

    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ensure_staff(restaurant_id: int, user) -> dict:
    name = user.first_name or str(user.id)
    return get_or_register_staff(restaurant_id, str(user.id), name)


async def _require_restaurant(update: Update):
    chat_id = str(update.effective_chat.id)
    restaurant = get_restaurant_by_group(chat_id)
    if not restaurant:
        await update.message.reply_text("Please /register this group first.")
        return None
    return restaurant


def _default_due_date(invoice_date: str | None, payment_terms: str | None) -> str | None:
    """
    Calculate a due date from invoice date and payment terms.
    Defaults to Net 30 if no terms are specified.
    """
    base = None
    if invoice_date:
        try:
            base = datetime.strptime(invoice_date, "%Y-%m-%d").date()
        except ValueError:
            pass
    if not base:
        base = date.today()

    # Parse days from terms like "Net 30", "30 days", "due in 14 days"
    days = 30  # default
    if payment_terms:
        m = re.search(r"(\d+)", payment_terms)
        if m:
            days = int(m.group(1))

    return str(base + timedelta(days=days))


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to Restaurant-IQ!\n\n"
        "I capture operational data from your team and turn it into weekly intelligence briefings.\n\n"
        "SETUP:\n"
        "  /register YourRestaurantName — Register this group\n\n"
        "DAILY USE (just send me):\n"
        "  Voice note — Shift update, observations, issues\n"
        "  Photo       — Invoice, receipt, delivery note\n"
        "  Text        — Any quick update\n\n"
        "REPORTS & QUERIES:\n"
        "  /weeklyreport          — Full weekly briefing + P&L (PDF included)\n"
        "  /financials            — Revenue vs costs for any period\n"
        "  /recall 5 May          — What happened on a specific date\n"
        "  /recall last week      — Summary of last week\n"
        "  /recall March          — Everything recorded in March\n"
        "  /status                — Entries captured this week\n\n"
        "INVOICES:\n"
        "  /outstanding           — List unpaid invoices\n"
        "  /markpaid 12           — Mark invoice #12 as paid\n\n"
        "Every message from any team member in this group is captured and analysed.\n\n"
        "Type /features for a full guide to everything the bot can do."
    )


async def cmd_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /register YourRestaurantName\nExample: /register Joe's Bistro")
        return

    name = " ".join(context.args)
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)

    register_restaurant(name, chat_id, user_id)
    restaurant = get_restaurant_by_group(chat_id)
    if restaurant:
        register_staff(restaurant["id"], user_id, update.effective_user.first_name or "Owner", "owner")

    await update.message.reply_text(
        f"Registered: {name}\n"
        f"You are set as the owner.\n\n"
        f"All team members can now just send messages to this group.\n"
        f"Voice notes, photos and texts are all captured automatically.\n\n"
        f"Try sending a voice note about today's shift!"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    entries = get_week_entries(restaurant["id"])

    categories: dict = {}
    for e in entries:
        cat = e["category"] or "general"
        categories[cat] = categories.get(cat, 0) + 1

    today = datetime.now()
    week_start_str = (today - timedelta(days=today.weekday())).strftime("%A %d %B")

    lines = [f"  {cat}: {count}" for cat, count in sorted(categories.items())]
    cat_summary = "\n".join(lines) if lines else "  None yet"

    # Outstanding invoices count
    outstanding = get_outstanding_invoices(restaurant["id"])
    invoice_line = f"Unpaid invoices: {len(outstanding)}" if outstanding else "Unpaid invoices: none"

    tier = get_tier_status()
    next_info = (
        f"Next upgrade: {tier['next_tier']} at {tier['next_at']} restaurants"
        if tier.get("next_at") else "You are on the top tier."
    )

    await update.message.reply_text(
        f"Restaurant-IQ — {restaurant['name']}\n"
        f"Week from: {week_start_str}\n\n"
        f"Entries captured: {len(entries)}\n"
        f"By category:\n{cat_summary}\n\n"
        f"{invoice_line}\n\n"
        f"AI Tier: {tier['label']}\n"
        f"Restaurants registered: {tier['count']}\n"
        f"{next_info}\n\n"
        f"Keep the data coming — voice notes, photos and texts all count!"
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /today — list every entry logged today with who sent it, what time, and what was captured.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    today_str = date.today().isoformat()
    entries = get_entries_with_staff(restaurant["id"], today_str, today_str)

    if not entries:
        await update.message.reply_text(
            "No entries logged today yet.\n"
            "Send a voice note, photo or text to start capturing."
        )
        return

    TYPE_ICON = {"voice": "🎙", "photo": "📷", "text": "💬"}
    lines = []
    for e in entries:
        icon = TYPE_ICON.get(e["entry_type"], "📝")
        name = e["staff_name"] or "Unknown"
        time_str = e["entry_time"][:5] if e["entry_time"] else ""
        category = e["category"] or "general"

        # Get the AI summary if available, otherwise truncate raw text
        summary = ""
        if e["structured_data"]:
            try:
                a = json.loads(e["structured_data"])
                summary = a.get("summary", "")
            except (json.JSONDecodeError, AttributeError):
                pass
        if not summary:
            summary = (e["raw_text"] or "")[:80]

        lines.append(f"{icon} {time_str}  {name}  [{category}]\n   {summary}")

    body = "\n\n".join(lines)
    await update.message.reply_text(
        f"Today's entries — {restaurant['name']}\n"
        f"{date.today().strftime('%A %d %B')}\n"
        f"{'─' * 36}\n\n"
        f"{body}\n\n"
        f"Total: {len(entries)} entries from {len({e['staff_name'] for e in entries})} team member(s)"
    )


async def cmd_correct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /correct [correction text]
    Fix a specific detail in the sender's last entry without re-sending the whole thing.
    The correction is appended to the original text and the AI re-analyses the combined version.

    Example:
      /correct the beef price was £450 not £540
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /correct [what needs fixing]\n\n"
            "Example:\n"
            "  /correct the beef was £450 not £540\n"
            "  /correct supplier was City Farm not Fresh Greens\n\n"
            "This updates your last entry without re-sending the whole thing."
        )
        return

    staff = _ensure_staff(restaurant["id"], update.effective_user)
    last = get_last_entry(restaurant["id"], staff["id"])

    if not last:
        await update.message.reply_text(
            "No previous entry found to correct. Send your full message first."
        )
        return

    correction = " ".join(context.args)
    original_text = last["raw_text"] or ""
    corrected_text = f"{original_text}\n\nCORRECTION: {correction}"

    await update.message.reply_text("Updating your entry with the correction...")

    analysis = analyze_text_entry(corrected_text, restaurant["name"])
    update_entry(last["id"], corrected_text, json.dumps(analysis), analysis.get("category", last["category"]))

    urgency = analysis.get("urgency", "low")
    icon = URGENCY_ICONS.get(urgency, "⚪")
    summary = analysis.get("summary", corrected_text[:100])

    await update.message.reply_text(
        f"Entry updated with your correction.\n\n"
        f"Correction applied: {correction}\n\n"
        f"New summary: {summary}\n"
        f"Category: {analysis.get('category', 'general')}\n"
        f"Urgency: {icon} {urgency}\n\n"
        f"Still wrong? Use /correct again or /deletelast to start over."
    )


async def cmd_deletelast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /deletelast — remove the sender's most recent entry so they can re-send it correctly.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    staff = _ensure_staff(restaurant["id"], update.effective_user)
    deleted = delete_last_entry(restaurant["id"], staff["id"])

    if not deleted:
        await update.message.reply_text("No entries found to delete.")
        return

    preview = (deleted["raw_text"] or "")[:120]
    await update.message.reply_text(
        f"Deleted your last {deleted['entry_type']} entry:\n"
        f'"{preview}"\n\n'
        "Now re-send your corrected message."
    )


async def cmd_weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    entries = get_week_entries(restaurant["id"])
    if not entries:
        await update.message.reply_text(
            "No data captured this week yet.\n"
            "Send voice notes, photos or text updates first, then run /weeklyreport again."
        )
        return

    await update.message.reply_text(
        f"Generating weekly briefing from {len(entries)} entries...\n"
        "This may take 1-2 minutes while the AI analyses everything."
    )

    # Build entries list and financials for the report
    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    week_end = today.strftime("%Y-%m-%d")

    financials = get_financial_summary(restaurant["id"], week_start, week_end)

    entries_data = []
    for e in entries:
        entry = {
            "date": e["entry_date"],
            "time": e["entry_time"],
            "type": e["entry_type"],
            "raw_text": e["raw_text"] or "",
        }
        if e["structured_data"]:
            try:
                entry["analysis"] = json.loads(e["structured_data"])
            except json.JSONDecodeError:
                pass
        entries_data.append(entry)

    report_text = generate_weekly_report(entries_data, restaurant["name"], financials)

    save_weekly_report(restaurant["id"], week_start, week_end, report_text)

    # Generate PDF
    safe_name = restaurant["name"].replace(" ", "_").replace("/", "-")
    pdf_path = os.path.join(REPORTS_DIR, f"{safe_name}_{week_start}.pdf")
    generate_pdf_report(report_text, restaurant["name"], week_start, week_end, pdf_path)

    # Send text report (split if over Telegram's 4096 char limit)
    header = f"RESTAURANT-IQ WEEKLY BRIEFING\n{'=' * 34}\n\n"
    full_message = header + report_text
    if len(full_message) <= 4096:
        await update.message.reply_text(full_message)
    else:
        await update.message.reply_text(full_message[:4000] + "\n\n[continued in PDF...]")

    # Send PDF
    with open(pdf_path, "rb") as pdf_file:
        await update.message.reply_document(
            document=pdf_file,
            filename=os.path.basename(pdf_path),
            caption=f"Weekly briefing for {restaurant['name']} — {_fmt_date(week_start)}",
        )


async def cmd_recall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /recall [date or period]
    Examples:
      /recall 5 May
      /recall 25th March 2026
      /recall last week
      /recall March
      /recall today
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /recall [date or period]\n\n"
            "Examples:\n"
            "  /recall today\n"
            "  /recall yesterday\n"
            "  /recall 5 May\n"
            "  /recall 25th March 2026\n"
            "  /recall last week\n"
            "  /recall March\n"
            "  /recall March 2026"
        )
        return

    query_text = " ".join(context.args)
    date_range = _parse_date_range(query_text)

    if not date_range:
        await update.message.reply_text(
            f"Couldn't understand the date \"{query_text}\".\n\n"
            "Try formats like: 5 May, 25th March, last week, this month, March 2026"
        )
        return

    start_date, end_date = date_range
    entries = get_entries_for_period(restaurant["id"], start_date, end_date)

    if not entries:
        period_label = query_text if start_date == end_date else f"{start_date} to {end_date}"
        await update.message.reply_text(
            f"No entries found for {period_label}.\n"
            "Either no data was recorded then, or it was before this restaurant was registered."
        )
        return

    await update.message.reply_text(
        f"Found {len(entries)} entries for {query_text}. Summarising..."
    )

    # Build entries_data for the recall summary
    entries_data = []
    for e in entries:
        item = {
            "date": e["entry_date"],
            "time": e["entry_time"],
            "type": e["entry_type"],
            "raw_text": e["raw_text"] or "",
        }
        if e["structured_data"]:
            try:
                item["analysis"] = json.loads(e["structured_data"])
            except json.JSONDecodeError:
                pass
        entries_data.append(item)

    summary = generate_recall_summary(entries_data, query_text, restaurant["name"])

    period_label = start_date if start_date == end_date else f"{start_date} to {end_date}"
    await update.message.reply_text(
        f"Recall: {restaurant['name']} — {period_label}\n"
        f"({len(entries)} entries)\n\n"
        f"{summary}"
    )


async def cmd_financials(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /financials            → this week
    /financials this month → month to date
    /financials last month → previous calendar month
    /financials March 2026 → specific month
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    query = " ".join(context.args).strip() if context.args else "this week"
    date_range = _parse_date_range(query)

    if not date_range:
        await update.message.reply_text(
            f"Couldn't understand period \"{query}\".\n"
            "Try: this week, this month, last month, March 2026"
        )
        return

    start_date, end_date = date_range
    fin = get_financial_summary(restaurant["id"], start_date, end_date)

    if fin["revenue_total"] == 0 and fin["cost_total"] == 0:
        await update.message.reply_text(
            f"No financial data found for {query} ({start_date} to {end_date}).\n\n"
            "Revenue is captured from voice/text updates mentioning covers and takings.\n"
            "Costs are captured when invoice photos are sent."
        )
        return

    period_label = query if start_date == end_date else f"{start_date} to {end_date}"
    cost_lines = ""
    if fin["cost_items"]:
        cost_lines = "\nInvoices captured:\n" + "\n".join(
            f"  {item['date']}  {item['supplier']:.<30} £{item['amount']:>8,.2f}"
            for item in fin["cost_items"]
        )

    margin_note = ""
    if fin["gross_margin_pct"] > 0:
        if fin["gross_margin_pct"] > 70:
            margin_note = "  ✅ Margin looks healthy — note costs may be incomplete."
        elif fin["gross_margin_pct"] > 50:
            margin_note = "  🟡 Moderate margin — review cost capture completeness."
        else:
            margin_note = "  🔴 Margin looks tight — check all invoices have been photographed."

    outstanding = get_outstanding_invoices(restaurant["id"])
    outstanding_total = sum(inv["total_amount"] or 0 for inv in outstanding)
    outstanding_line = (
        f"\nOutstanding invoices (unpaid): {len(outstanding)} totalling £{outstanding_total:,.2f}"
        if outstanding else "\nAll captured invoices: paid ✅"
    )

    await update.message.reply_text(
        f"Financial Summary — {restaurant['name']}\n"
        f"Period: {period_label}\n"
        f"{'─' * 40}\n\n"
        f"Revenue captured:        £{fin['revenue_total']:>10,.2f}\n"
        f"Invoiced costs captured: £{fin['cost_total']:>10,.2f}\n"
        f"{'─' * 40}\n"
        f"Gross profit:            £{fin['gross_profit']:>10,.2f}\n"
        f"Gross margin:            {fin['gross_margin_pct']:>9.1f}%\n"
        f"{margin_note}"
        f"{outstanding_line}"
        f"{cost_lines}\n\n"
        f"Note: revenue = reported takings from voice/text updates.\n"
        f"Costs = invoices photographed. Labour costs not captured here."
    )


async def cmd_outstanding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all unpaid invoices sorted by due date."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    invoices = get_outstanding_invoices(restaurant["id"])

    if not invoices:
        await update.message.reply_text(
            "No outstanding invoices.\n\n"
            "All captured invoices have been marked as paid, or no invoices have been photographed yet.\n"
            "Send a photo of any invoice to start tracking."
        )
        return

    today = date.today()
    lines = []
    total = 0.0
    for inv in invoices:
        amount = inv["total_amount"] or 0
        total += amount
        due = inv["due_date"] or "No due date"
        if inv["due_date"]:
            try:
                due_d = datetime.strptime(inv["due_date"], "%Y-%m-%d").date()
                days = (due_d - today).days
                if days < 0:
                    flag = f"⚠️ OVERDUE {abs(days)}d"
                elif days == 0:
                    flag = "🔴 DUE TODAY"
                elif days <= 3:
                    flag = f"🟡 Due in {days}d"
                else:
                    flag = f"🟢 Due {_fmt_date(inv['due_date'])}"
            except ValueError:
                flag = f"Due {due}"
        else:
            flag = "No due date"

        lines.append(f"#{inv['id']}  {(inv['supplier_name'] or 'Unknown'):.<25} £{amount:>8,.2f}  {flag}")

    invoices_text = "\n".join(lines)
    await update.message.reply_text(
        f"Outstanding Invoices — {restaurant['name']}\n"
        f"{'─' * 40}\n"
        f"{invoices_text}\n"
        f"{'─' * 40}\n"
        f"Total outstanding: £{total:,.2f}\n\n"
        f"To mark an invoice as paid: /markpaid [id]\n"
        f"Example: /markpaid {invoices[0]['id']}"
    )


async def cmd_markpaid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark an invoice as paid. Usage: /markpaid 12"""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: /markpaid [invoice id]\n\n"
            "Get invoice IDs from /outstanding"
        )
        return

    invoice_id = int(context.args[0])

    # Verify the invoice belongs to this restaurant
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM invoices WHERE id = ? AND restaurant_id = ?",
        (invoice_id, restaurant["id"]),
    )
    inv = cur.fetchone()
    conn.close()

    if not inv:
        await update.message.reply_text(
            f"Invoice #{invoice_id} not found.\n"
            "Check the ID with /outstanding"
        )
        return

    if inv["paid"]:
        await update.message.reply_text(
            f"Invoice #{invoice_id} ({inv['supplier_name']}, £{inv['total_amount']:.2f}) "
            f"was already marked paid on {inv['paid_date']}."
        )
        return

    mark_invoice_paid(invoice_id)
    await update.message.reply_text(
        f"Invoice #{invoice_id} marked as paid.\n"
        f"Supplier: {inv['supplier_name'] or 'Unknown'}\n"
        f"Amount: £{(inv['total_amount'] or 0):.2f}\n"
        f"Paid date: {date.today().strftime('%-d %B %Y')}\n\n"
        f"Run /outstanding to see remaining unpaid invoices."
    )


# ── Features guide ────────────────────────────────────────────────────────────

async def cmd_features(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /features — plain-English guide to what the bot does, how to use it,
    what it captures, and what it cannot do. Split into 4 messages.
    """

    # Message 1: What you can send
    await update.message.reply_text(
        "RESTAURANT-IQ — WHAT THIS BOT DOES\n"
        "════════════════════════════════════\n\n"
        "Your team sends messages to this group as normal.\n"
        "The bot reads every message, extracts the useful data,\n"
        "and builds a picture of your restaurant's week.\n"
        "No forms. No spreadsheets. Just talk.\n\n"
        "────────────────────────────────────\n"
        "WHAT YOU CAN SEND\n"
        "────────────────────────────────────\n\n"
        "1. VOICE NOTES\n"
        "Hold the mic button in Telegram and speak.\n"
        "Any team member can do this — no training needed.\n\n"
        "Good examples:\n"
        "  \"Tonight we did 82 covers. Revenue around £2,600. "
        "Lamb sold out by 8pm. One complaint about wait time on table 4.\"\n\n"
        "  \"Delivery from Metro Supplies. Short on salmon — only 6kg of the "
        "14kg ordered. Invoice was £290.\"\n\n"
        "  \"Fridge in prep kitchen is making a noise. Needs checking tomorrow.\"\n\n"
        "2. INVOICE OR RECEIPT PHOTOS\n"
        "Photograph any invoice or delivery note and send it here.\n"
        "The AI reads supplier, total, VAT and line items automatically.\n"
        "It starts tracking the payment due date straight away.\n\n"
        "Works for: supplier invoices, delivery dockets, utility bills, repair invoices.\n"
        "Best results: photo flat, good light, all four corners visible.\n\n"
        "3. TEXT MESSAGES\n"
        "Type anything — the bot captures and categorises it.\n\n"
        "Examples:\n"
        "  \"Butcher raised beef prices by 9% this week\"\n"
        "  \"Ahmed was 40 mins late — third time this month\"\n"
        "  \"Truffle arancini selling really well, customers loving it\"\n"
        "  \"Saturday: 96 covers, £3,250 takings\""
    )

    # Message 2: What gets extracted + limitations
    await update.message.reply_text(
        "WHAT THE BOT EXTRACTS AUTOMATICALLY\n"
        "══════════════════════════════════════\n\n"
        "You don't need a special format. The AI understands plain speech.\n\n"
        "REVENUE\n"
        "  Covers and takings from any message.\n"
        "  \"Did 90 covers, took about £3,100\" → logged as revenue.\n\n"
        "COSTS\n"
        "  Invoice totals from photos — recorded to the penny.\n"
        "  Price increases mentioned in voice or text — flagged for review.\n\n"
        "WASTE\n"
        "  Items that sold out (86'd) — reveals over/under ordering patterns.\n"
        "  Food waste mentioned explicitly — logged by date.\n\n"
        "STAFF\n"
        "  Lateness, absences, performance concerns — logged with date.\n"
        "  Positive mentions captured too — a record of who is doing well.\n\n"
        "SUPPLIER ISSUES\n"
        "  Short deliveries, quality problems, price changes — all flagged.\n\n"
        "EQUIPMENT & OPERATIONS\n"
        "  Kit faults, complaints, compliments — stored and summarised weekly.\n\n"
        "URGENCY FLAG on every entry:\n"
        "  🔴 High — needs attention now\n"
        "  🟡 Medium — worth watching\n"
        "  🟢 Low — noted for weekly review\n\n"
        "────────────────────────────────────\n"
        "WHAT IT CANNOT CAPTURE\n"
        "────────────────────────────────────\n\n"
        "  ✗ Revenue you don't report — only knows what your team tells it\n"
        "  ✗ Staff hours or wages — no labour cost tracking\n"
        "  ✗ Till or EPOS data — no integration with payment systems\n"
        "  ✗ Blurry or dark invoice photos — AI cannot read unclear images\n"
        "  ✗ Non-English voice notes — transcription works best in English\n"
        "  ✗ Multiple currencies — assumes £ throughout"
    )

    # Message 3: Commands
    await update.message.reply_text(
        "COMMANDS YOU CAN USE\n"
        "═════════════════════\n\n"
        "/weeklyreport\n"
        "  Full AI briefing for the current week.\n"
        "  Covers: revenue, cost alerts, waste patterns, staff issues,\n"
        "  supplier flags, and a numbered action list by financial impact.\n"
        "  Also sends a branded PDF you can save, print or share.\n\n"
        "/financials [period]\n"
        "  P&L for any period — revenue vs invoiced costs = gross profit.\n"
        "  Try: /financials   /financials this month   /financials March 2026\n\n"
        "/recall [date or period]\n"
        "  Ask the bot what happened on any day or week.\n"
        "  The AI summarises all entries for that period.\n"
        "  Try: /recall yesterday   /recall 5 May   /recall last week   /recall March\n\n"
        "/outstanding\n"
        "  All unpaid invoices sorted by due date.\n"
        "  Shows supplier, amount, and days until due (or days overdue).\n"
        "  The bot also sends an automatic 9am reminder to this group\n"
        "  when any invoice is due within 3 days or is overdue.\n\n"
        "/markpaid [invoice number]\n"
        "  Mark an invoice as settled. Get the number from /outstanding.\n"
        "  Example: /markpaid 14\n\n"
        "/status\n"
        "  Quick count of entries captured this week by category.\n"
        "  Useful to check the team is actually sending updates.\n\n"
        "/demo\n"
        "  Loads a realistic week of demo data so you can see exactly\n"
        "  what all the reports look like before going live.\n"
        "  Run /demoreset to clear it when done."
    )

    # Message 4: How to get the most out of it
    await update.message.reply_text(
        "HOW TO GET THE MOST OUT OF IT\n"
        "══════════════════════════════\n\n"
        "THE MOST VALUABLE HABIT:\n"
        "End-of-shift voice note from whoever closes the restaurant.\n"
        "Even 30 seconds covering covers, any issues, and the feel of service\n"
        "gives the AI enough to produce sharp weekly insights.\n\n"
        "INVOICES:\n"
        "Photograph every invoice the day it arrives — not in batches.\n"
        "The bot tracks due dates from the invoice date, so late uploads\n"
        "mean you miss payment warnings.\n\n"
        "YOUR TEAM:\n"
        "Add all staff to this Telegram group.\n"
        "The bot records who sent each update, so the weekly report\n"
        "can link issues and wins to the right shifts and people.\n\n"
        "WHAT GOOD ENTRIES LOOK LIKE:\n"
        "  ✅ \"Friday lunch: 44 covers, £1,180. Veg soup sold out at 1pm.\n"
        "       Two tables complimented the new sea bass.\"\n\n"
        "  ✅ [Photo of invoice — flat on desk, clear light, full page visible]\n\n"
        "  ✅ \"Walk-in fridge alarm at 6am — engineer confirmed false alarm.\"\n\n"
        "WHAT THE BOT IGNORES:\n"
        "  ✗ Short replies like \"ok\" or \"thanks\" — no useful data\n"
        "  ✗ Forwarded articles or links\n"
        "  ✗ Messages sent in any other group — only reads this one\n\n"
        "────────────────────────────────────\n"
        "The more your team reports, the sharper your weekly briefing.\n"
        "Type /demo to see the full output with realistic data right now."
    )


# ── Message handlers ──────────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    staff = _ensure_staff(restaurant["id"], update.effective_user)

    voice = update.message.voice or update.message.audio
    file = await voice.get_file()
    file_path = os.path.join(VOICE_DIR, f"{voice.file_unique_id}.ogg")
    await file.download_to_drive(file_path)

    await update.message.reply_text(
        f"Got your voice note, {update.effective_user.first_name}. Transcribing..."
    )

    try:
        text = transcribe_audio(file_path)
        if not text:
            await update.message.reply_text("Could not transcribe — audio may be too short or unclear.")
            return

        analysis = analyze_text_entry(text, restaurant["name"])
        save_entry(
            restaurant["id"],
            staff["id"],
            "voice",
            text,
            json.dumps(analysis),
            analysis.get("category", "general"),
        )

        urgency = analysis.get("urgency", "low")
        icon = URGENCY_ICONS.get(urgency, "⚪")
        summary = analysis.get("summary", text[:100])

        await update.message.reply_text(
            f"Captured ({update.effective_user.first_name}):\n"
            f'"{text[:200]}"\n\n'
            f"Category: {analysis.get('category', 'general')}\n"
            f"Summary: {summary}\n"
            f"Urgency: {icon} {urgency}\n\n"
            f"Wrong detail? /correct the beef was £450 not £540\nWrong entry? /deletelast and re-send."
        )
    finally:
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    staff = _ensure_staff(restaurant["id"], update.effective_user)

    photo = update.message.photo[-1]
    file = await photo.get_file()
    file_path = os.path.join(PHOTO_DIR, f"{photo.file_unique_id}.jpg")
    await file.download_to_drive(file_path)

    await update.message.reply_text("Got the photo. Reading it now...")

    try:
        analysis = analyze_invoice_photo(file_path, restaurant["name"])
        raw_text = (
            f"Photo from {update.effective_user.first_name}: "
            f"{analysis.get('summary', 'Document captured')}"
        )
        entry_id = save_entry(
            restaurant["id"],
            staff["id"],
            "photo",
            raw_text,
            json.dumps(analysis),
            analysis.get("category", "cost"),
        )

        # Auto-track invoice for payment reminders and P&L
        if analysis.get("total_amount") and analysis.get("total_amount", 0) > 0:
            due_date = analysis.get("due_date") or _default_due_date(
                analysis.get("date"), analysis.get("payment_terms")
            )
            save_invoice(
                restaurant["id"],
                entry_id,
                analysis.get("supplier_name", "Unknown"),
                analysis.get("date", str(date.today())),
                due_date,
                analysis.get("total_amount", 0),
                analysis.get("vat", 0),
                analysis.get("summary", ""),
            )

        supplier = analysis.get("supplier_name") or "Unknown"
        total = analysis.get("total_amount")
        total_str = f"£{total:.2f}" if total else "Not found"
        raw_due = analysis.get("due_date")
        due_str = f"\nPayment due: {_fmt_date(raw_due) if raw_due else 'defaulting to 30 days'}" if total else ""

        await update.message.reply_text(
            f"Invoice / Receipt Captured:\n"
            f"Supplier: {supplier}\n"
            f"Total: {total_str}{due_str}\n"
            f"Summary: {analysis.get('summary', 'Document logged')}\n\n"
            f"Added to invoices — track with /outstanding\n"
            f"Wrong amount or supplier? /correct the total was £340 not £430\n"
            f"Wrong photo entirely? /deletelast and re-send a clearer one."
        )
    finally:
        try:
            os.remove(file_path)
        except FileNotFoundError:
            pass


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    text = update.message.text
    staff = _ensure_staff(restaurant["id"], update.effective_user)

    analysis = analyze_text_entry(text, restaurant["name"])
    save_entry(
        restaurant["id"],
        staff["id"],
        "text",
        text,
        json.dumps(analysis),
        analysis.get("category", "general"),
    )

    urgency = analysis.get("urgency", "low")
    icon = URGENCY_ICONS.get(urgency, "⚪")
    summary = analysis.get("summary", text[:80])
    await update.message.reply_text(
        f"Captured ({update.effective_user.first_name}):\n"
        f'"{text[:200]}"\n\n'
        f"Category: {analysis.get('category', 'general')}\n"
        f"Summary: {summary}\n"
        f"Urgency: {icon} {urgency}\n\n"
        f"Wrong detail? /correct the beef was £450 not £540\nWrong entry? /deletelast and re-send."
    )


# ── Scheduled jobs ────────────────────────────────────────────────────────────

async def _invoice_reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Runs daily at 9am.
    Sends payment reminders to each restaurant group for invoices that are
    overdue or due within the next 3 days.
    """
    today = date.today()
    due_soon = get_invoices_due_soon(days_ahead=3)

    # Group by restaurant (avoid spamming one group with multiple messages)
    by_restaurant: dict = {}
    for inv in due_soon:
        chat_id = inv["telegram_group_id"]
        if chat_id not in by_restaurant:
            by_restaurant[chat_id] = {"name": inv["restaurant_name"], "invoices": []}
        by_restaurant[chat_id]["invoices"].append(inv)

    for chat_id, data in by_restaurant.items():
        lines = []
        for inv in data["invoices"]:
            amount = inv["total_amount"] or 0
            if inv["due_date"]:
                try:
                    due_d = datetime.strptime(inv["due_date"], "%Y-%m-%d").date()
                    days = (due_d - today).days
                except ValueError:
                    days = 0
            else:
                days = 0

            if days < 0:
                lines.append(f"⚠️ OVERDUE {abs(days)} days: {inv['supplier_name']} — £{amount:,.2f} (ID #{inv['id']})")
            elif days == 0:
                lines.append(f"🔴 DUE TODAY: {inv['supplier_name']} — £{amount:,.2f} (ID #{inv['id']})")
            else:
                lines.append(f"🟡 Due in {days} days ({_fmt_date(inv['due_date'])}): {inv['supplier_name']} — £{amount:,.2f} (ID #{inv['id']})")

        if lines:
            msg = (
                f"💳 Invoice Payment Reminder — {data['name']}\n\n"
                + "\n".join(lines)
                + "\n\nMark as paid: /markpaid [id]   |   Full list: /outstanding"
            )
            try:
                await context.bot.send_message(chat_id=chat_id, text=msg)
            except Exception as e:
                logger.warning("Could not send invoice reminder to %s: %s", chat_id, e)


# ── Demo commands ─────────────────────────────────────────────────────────────

DEMO_RESTAURANT_NAME = "The Golden Fork"
DEMO_GROUP_PREFIX = "DEMO_"


async def cmd_demo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Load a full week of pre-built realistic demo data into this chat."""
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)

    await update.message.reply_text(
        "Setting up demo data for The Golden Fork...\n"
        "This takes just a second."
    )

    register_restaurant(DEMO_RESTAURANT_NAME, chat_id, user_id)
    restaurant = get_restaurant_by_group(chat_id)
    if not restaurant:
        await update.message.reply_text("Failed to create demo restaurant. Please try again.")
        return

    staff_map: dict[str, int] = {}
    for i, member in enumerate(DEMO_STAFF):
        fake_user_id = f"DEMO_STAFF_{i}_{restaurant['id']}"
        register_staff(restaurant["id"], fake_user_id, member["name"], member["role"])
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM staff WHERE restaurant_id = ? AND telegram_user_id = ?",
            (restaurant["id"], fake_user_id),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            staff_map[member["name"]] = row["id"]

    entries = get_demo_entries()
    conn = get_connection()
    cur = conn.cursor()
    for e in entries:
        staff_id = staff_map.get(e["staff_name"], staff_map.get("Jake"))
        cur.execute(
            """INSERT INTO daily_entries
               (restaurant_id, staff_id, entry_date, entry_time, entry_type,
                raw_text, structured_data, category)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                restaurant["id"],
                staff_id,
                e["entry_date"],
                e["entry_time"],
                e["entry_type"],
                e["raw_text"],
                e["structured_data"],
                e["category"],
            ),
        )
        entry_id = cur.lastrowid

        # Auto-populate invoices table from demo photo entries
        if e["entry_type"] == "photo" and e["category"] == "cost":
            try:
                data = json.loads(e["structured_data"])
                if data.get("total_amount"):
                    invoice_date = data.get("date", e["entry_date"])
                    due_date = data.get("due_date") or _default_due_date(
                        invoice_date, data.get("payment_terms")
                    )
                    cur.execute(
                        """INSERT INTO invoices
                           (restaurant_id, entry_id, supplier_name, invoice_date, due_date,
                            total_amount, vat, description)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            restaurant["id"],
                            entry_id,
                            data.get("supplier_name", "Unknown"),
                            invoice_date,
                            due_date,
                            data["total_amount"],
                            data.get("vat", 0),
                            data.get("summary", ""),
                        ),
                    )
            except (json.JSONDecodeError, KeyError):
                pass

    conn.commit()
    conn.close()

    categories: dict = {}
    for e in entries:
        cat = e["category"]
        categories[cat] = categories.get(cat, 0) + 1

    cat_lines = "\n".join(f"  {cat}: {count}" for cat, count in sorted(categories.items()))

    await update.message.reply_text(
        f"Demo loaded for: {DEMO_RESTAURANT_NAME}\n"
        f"{'=' * 36}\n\n"
        f"Team: Jake (owner), Sophie, Marcus, Elena\n\n"
        f"{len(entries)} entries across Mon–Sun:\n"
        f"{cat_lines}\n\n"
        f"This week's storylines:\n"
        f"  • Supplier switched: Fresh Greens → City Farm Direct (saving £31/wk)\n"
        f"  • Dishwasher fault Wed → repaired Friday, just in time for record weekend\n"
        f"  • Marcus performance issue → improvement plan → faultless by Saturday\n"
        f"  • New lamb dish becoming the signature — 18 orders on Friday alone\n"
        f"  • Saturday record: 98 covers, £3,180 — best service ever\n"
        f"  • Week total: ~820 covers, ~£27,000 revenue (+20% week-on-week)\n\n"
        f"Demo steps:\n"
        f"  1. /status          → entries + outstanding invoices\n"
        f"  2. /outstanding     → unpaid invoice tracker\n"
        f"  3. /financials      → P&L summary for the week\n"
        f"  4. /recall 5 May    → recall a specific date (use a date from this week)\n"
        f"  5. /weeklyreport    → full intelligence briefing + PDF\n\n"
        f"Run /demoreset to clear all data when done."
    )


async def cmd_demoreset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove all data associated with the demo restaurant in this chat."""
    chat_id = str(update.effective_chat.id)
    restaurant = get_restaurant_by_group(chat_id)
    if not restaurant:
        await update.message.reply_text("No restaurant registered in this chat.")
        return

    conn = get_connection()
    cur = conn.cursor()
    rid = restaurant["id"]

    cur.execute("DELETE FROM invoices WHERE restaurant_id = ?", (rid,))
    cur.execute("DELETE FROM daily_entries WHERE restaurant_id = ?", (rid,))
    cur.execute("DELETE FROM weekly_reports WHERE restaurant_id = ?", (rid,))
    cur.execute("DELETE FROM staff WHERE restaurant_id = ?", (rid,))
    cur.execute("DELETE FROM restaurants WHERE id = ?", (rid,))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        "Demo reset complete.\n"
        "All data removed. Run /register to start fresh, or /demo to reload demo data."
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    init_db()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("register", cmd_register))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("correct", cmd_correct))
    app.add_handler(CommandHandler("deletelast", cmd_deletelast))
    app.add_handler(CommandHandler("weeklyreport", cmd_weekly_report))
    app.add_handler(CommandHandler("recall", cmd_recall))
    app.add_handler(CommandHandler("financials", cmd_financials))
    app.add_handler(CommandHandler("outstanding", cmd_outstanding))
    app.add_handler(CommandHandler("markpaid", cmd_markpaid))
    app.add_handler(CommandHandler("demo", cmd_demo))
    app.add_handler(CommandHandler("demoreset", cmd_demoreset))
    app.add_handler(CommandHandler("features", cmd_features))

    # Messages — voice before text
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Daily invoice reminder at 9am
    app.job_queue.run_daily(
        _invoice_reminder_job,
        time=datetime.strptime("09:00", "%H:%M").time(),
        name="invoice_reminders",
    )

    logger.info("Restaurant-IQ Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
