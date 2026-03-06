"""
Restaurant-IQ Telegram Bot
--------------------------
Entry point. Run with:  python bot.py

Handles:
  - /start              — welcome message
  - /register           — register this Telegram group as a restaurant
  - /status             — show entries captured this week
  - /weeklyreport       — generate and send the weekly intelligence briefing
  - /recall [date]      — recall what was recorded on a specific date or period
  - /financials         — P&L and cashflow summary for any period
  - /outstanding        — list all unpaid invoices with due dates
  - /markpaid [id]      — mark an invoice as paid
  - /demo               — load a realistic week of demo data for client presentations
  - /demoreset          — remove all demo data from this chat

UK Legal Compliance (unique to Restaurant-IQ):
  - /tips [period]      — tip events log (Employment (Allocation of Tips) Act 2023)
  - /tipsreport         — formal Tips Act compliance record (3-year retention duty)
  - /allergens          — allergen traceability log (Natasha's Law / FSA)
  - /resolvallergen [id]— mark an allergen alert as reviewed and resolved
  - /inspection         — FSA Food Hygiene inspection readiness report (90-day analysis)
  - /import [dates]: [description] — import historical data for any period (day, fortnight, month, quarter, etc)

Message types:
  - Voice notes  → transcribed by Whisper → analysed by AI → tips/allergens auto-logged
  - Photos       → analysed by AI vision (invoice/receipt reading) → allergens auto-flagged
  - Text         → analysed by AI fast model → tips/allergens auto-logged
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

from config import TELEGRAM_BOT_TOKEN, SUPPORT_CHAT_ID
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
    save_tip_event,
    get_tips_for_period,
    get_tips_summary,
    save_allergen_alert,
    get_allergen_alerts,
    resolve_allergen_alert,
    clear_all_entries,
    save_support_ticket,
    get_support_tickets,
    get_ticket_by_id,
    resolve_support_ticket,
    get_all_open_tickets,
    update_restaurant_name,
    # New features
    save_labour_entry,
    get_labour_for_period,
    get_labour_summary,
    save_invoice_line_items,
    detect_price_changes,
    get_all_restaurants,
    get_weekly_reports,
    get_report_by_week,
    get_staff_entry_counts,
    get_eightysix_trends,
    delete_entries_older_than,
)
from transcriber import transcribe_audio
from analyzer import analyze_text_entry, analyze_invoice_photo, generate_weekly_report
from model_router import (
    get_tier_status, generate_recall_summary, generate_tips_report,
    generate_inspection_report, analyze_correction, analyze_history_import,
    answer_help_question,
)
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

# Regex to extract monetary amounts like £450, £1,200, 1200, 1200.50
_re_amount = re.compile(r"£?([\d,]+(?:\.\d{1,2})?)")

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


# ── Compliance auto-logging ───────────────────────────────────────────────────

def _auto_log_compliance(restaurant_id: int, entry_id: int, analysis: dict, entry_date: str):
    """
    After every entry is saved, check AI analysis for tips and allergen flags.
    Log them to the relevant compliance tables automatically.
    Called from handle_voice, handle_photo, and handle_text.
    """
    # Tips Act compliance
    if analysis.get("tips_detected"):
        try:
            amount = float(analysis.get("tip_amount") or 0)
            tip_type = analysis.get("tip_type") or "unknown"
            notes = analysis.get("summary", "")
            save_tip_event(
                restaurant_id, entry_id, entry_date,
                shift=None, tip_type=tip_type,
                gross_amount=amount, staff_notes=notes,
            )
            logger.info("Tips Act: logged tip event £%.2f (%s) for restaurant %d", amount, tip_type, restaurant_id)
        except Exception as e:
            logger.warning("Failed to log tip event: %s", e)

    # Allergen alert (Natasha's Law)
    if analysis.get("allergen_risk"):
        try:
            save_allergen_alert(
                restaurant_id, entry_id, entry_date,
                supplier_name=analysis.get("supplier_name") or analysis.get("supplier_mentions", [None])[0] if analysis.get("supplier_mentions") else None,
                product_name=None,
                allergen_concern=analysis.get("allergen_detail") or "Possible allergen impact — review required",
            )
            logger.info("Allergen alert logged for restaurant %d: %s", restaurant_id, analysis.get("allergen_detail"))
        except Exception as e:
            logger.warning("Failed to log allergen alert: %s", e)


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
        "  /history               — Browse past weekly reports\n"
        "  /today                 — Everything logged today\n"
        "  /financials            — Revenue, costs, labour and net margin\n"
        "  /recall 5 May          — What happened on a specific date\n"
        "  /recall last week      — Summary of last week\n"
        "  /recall March          — Everything recorded in March\n"
        "  /status                — Entries captured this week\n\n"
        "COSTS & LABOUR:\n"
        "  /labour £450 wages Mon — Record wages or labour costs\n"
        "  /outstanding           — List unpaid invoices\n"
        "  /markpaid 12           — Mark invoice #12 as paid\n\n"
        "TEAM & MENU:\n"
        "  /teamstats             — Who's contributing and how much\n"
        "  /eightysix             — Most frequently 86'd menu items\n\n"
        "UK LEGAL COMPLIANCE:\n"
        "  /tips                  — Tips log (Tips Act 2023)\n"
        "  /tipsreport            — Formal tip allocation record\n"
        "  /allergens             — Allergen traceability log (Natasha's Law)\n"
        "  /inspection            — FSA inspection readiness report\n\n"
        "DATA MANAGEMENT:\n"
        "  /rename NewName        — Rename your restaurant\n"
        "  /import [dates]: [description] — Import any historical period\n"
        "  /export                — Export entries as CSV (for Excel/accountants)\n"
        "  /deletedata 90         — Delete entries older than 90 days (GDPR)\n"
        "  /cleardata CONFIRM     — Delete all entries and start fresh\n\n"
        "HELP & SUPPORT:\n"
        "  /ask [question]        — AI-powered help (anything about the bot)\n"
        "  /support [message]     — Contact the support team\n"
        "  /supportstatus         — Check your support tickets\n\n"
        "Every message from any team member in this group is captured and analysed.\n"
        "Tips and allergen risks are detected and logged automatically.\n"
        "Weekly reports are sent automatically every Monday at 08:00.\n\n"
        "Type /features for a full guide, or /ask [your question] for instant help."
    )


async def cmd_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /register YourRestaurantName\n"
            "Example: /register Joe's Bistro\n\n"
            "To change an existing name: /rename NewName\n"
            "To start completely fresh: /cleardata then /register NewName"
        )
        return

    name = " ".join(context.args)
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)

    existing = get_restaurant_by_group(chat_id)

    if existing:
        if existing["name"] == name:
            await update.message.reply_text(
                f"Already registered as '{name}'. No changes made.\n\n"
                f"Use /status to see your current data.\n"
                f"Use /rename NewName to change the name."
            )
            return

        # Different name — just rename, keep all data
        update_restaurant_name(chat_id, name)
        register_staff(existing["id"], user_id, update.effective_user.first_name or "Owner", "owner")
        await update.message.reply_text(
            f"Restaurant renamed to: {name}\n\n"
            f"All existing entries, invoices and records are preserved.\n"
            f"Use /status to verify everything looks correct.\n\n"
            f"If you want to delete all data and start fresh: /cleardata"
        )
        return

    # Fresh registration
    register_restaurant(name, chat_id, user_id)
    restaurant = get_restaurant_by_group(chat_id)
    if restaurant:
        register_staff(restaurant["id"], user_id, update.effective_user.first_name or "Owner", "owner")

    await update.message.reply_text(
        f"Registered: {name}\n"
        f"You are set as the owner.\n\n"
        f"All team members can now just send messages to this group.\n"
        f"Voice notes, photos and texts are all captured automatically.\n\n"
        f"Start by sending a voice note about today's shift.\n"
        f"Or type /features to see everything the bot can do."
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

    await update.message.reply_text("Applying your correction...")

    # Use a dedicated correction prompt — NOT the general analysis prompt.
    # The general prompt would read the correction as new data, not as a fix.
    analysis = analyze_correction(original_text, correction, restaurant["name"])
    # Store the corrected text cleanly — just the original with the fix noted
    corrected_text = f"{original_text} [corrected: {correction}]"
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

    period_fmt = _fmt_date(start_date) if start_date == end_date else f"{_fmt_date(start_date)} to {_fmt_date(end_date)}"

    if not entries:
        await update.message.reply_text(
            f"No entries found for {period_fmt}.\n"
            "Either no data was recorded then, or it was before this restaurant was registered."
        )
        return

    await update.message.reply_text(
        f"Found {len(entries)} entries for {period_fmt}. Summarising..."
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

    await update.message.reply_text(
        f"Recall: {restaurant['name']} — {period_fmt}\n"
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

    period_label = _fmt_date(start_date) if start_date == end_date else f"{_fmt_date(start_date)} to {_fmt_date(end_date)}"
    cost_lines = ""
    if fin["cost_items"]:
        cost_lines = "\nInvoices captured:\n" + "\n".join(
            f"  {item['date']}  {item['supplier']:.<30} £{item['amount']:>8,.2f}"
            for item in fin["cost_items"]
        )

    labour_lines = ""
    if fin.get("labour_items"):
        labour_lines = "\nLabour recorded:\n" + "\n".join(
            f"  {item['date']}  {(item['description'] or 'Labour'):.<30} £{item['amount']:>8,.2f}"
            for item in fin["labour_items"]
        )

    food_margin = fin.get("food_margin_pct", 0)
    net_margin = fin.get("net_margin_pct", 0)
    margin_note = ""
    if food_margin > 0:
        if food_margin > 70:
            margin_note = "  ✅ Food GP looks healthy — review labour % too."
        elif food_margin > 55:
            margin_note = "  🟡 Food GP moderate — check invoice capture completeness."
        else:
            margin_note = "  🔴 Food GP looks tight — review all costs and pricing."

    outstanding = get_outstanding_invoices(restaurant["id"])
    outstanding_total = sum(inv["total_amount"] or 0 for inv in outstanding)
    outstanding_line = (
        f"\nOutstanding invoices (unpaid): {len(outstanding)} totalling £{outstanding_total:,.2f}"
        if outstanding else "\nAll captured invoices: paid ✅"
    )

    labour_note = (
        f"\nLabour costs:            £{fin['labour_total']:>10,.2f}"
        if fin.get("labour_total", 0) > 0
        else "\nLabour costs:               not recorded — use /labour to add"
    )

    await update.message.reply_text(
        f"Financial Summary — {restaurant['name']}\n"
        f"Period: {period_label}\n"
        f"{'─' * 40}\n\n"
        f"Revenue captured:        £{fin['revenue_total']:>10,.2f}\n"
        f"Invoiced costs captured: £{fin['cost_total']:>10,.2f}\n"
        f"{labour_note}\n"
        f"{'─' * 40}\n"
        f"Net profit:              £{fin['gross_profit']:>10,.2f}\n"
        f"Food GP margin:          {food_margin:>9.1f}%\n"
        f"Net margin (inc labour): {net_margin:>9.1f}%\n"
        f"{margin_note}"
        f"{outstanding_line}"
        f"{cost_lines}"
        f"{labour_lines}\n\n"
        f"Note: revenue = reported takings. Costs = photographed invoices.\n"
        f"Labour = entries via /labour. Use /labour £X [description] to record wages."
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


# ── Data management commands ──────────────────────────────────────────────────

async def cmd_rename(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rename NewRestaurantName
    Change the restaurant name without losing any data.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if not context.args:
        await update.message.reply_text(
            f"Usage: /rename NewName\n\n"
            f"Current name: {restaurant['name']}\n"
            f"Example: /rename Kukua Kitchen"
        )
        return

    new_name = " ".join(context.args).strip()
    chat_id = str(update.effective_chat.id)
    update_restaurant_name(chat_id, new_name)

    await update.message.reply_text(
        f"Restaurant renamed.\n\n"
        f"Was: {restaurant['name']}\n"
        f"Now: {new_name}\n\n"
        f"All data is preserved. The new name will appear in all future reports."
    )


async def cmd_cleardata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /cleardata
    Delete all entries, invoices, and compliance records for this restaurant.
    Keeps the registration and restaurant name. Requires confirmation.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    # Require explicit confirmation to prevent accidental deletion
    if not context.args or context.args[0].upper() != "CONFIRM":
        entry_count = len(get_entries_for_period(
            restaurant["id"],
            "2000-01-01",
            date.today().isoformat(),
        ))
        outstanding = get_outstanding_invoices(restaurant["id"])
        await update.message.reply_text(
            f"This will permanently delete ALL data for {restaurant['name']}:\n\n"
            f"  Entries: {entry_count}\n"
            f"  Unpaid invoices: {len(outstanding)}\n"
            f"  All tips records, allergen alerts, and weekly reports\n\n"
            f"The restaurant registration and name are kept.\n\n"
            f"To confirm, type:\n"
            f"  /cleardata CONFIRM\n\n"
            f"This cannot be undone."
        )
        return

    clear_all_entries(restaurant["id"])
    await update.message.reply_text(
        f"All data cleared for {restaurant['name']}.\n\n"
        f"Your registration is intact — the bot will continue capturing new messages.\n"
        f"Use /import to backfill historical data if needed."
    )


# ── Help & onboarding commands ────────────────────────────────────────────────

async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /ask [your question]
    Ask anything about how the bot works. AI-powered help in plain English.

    Examples:
      /ask how do I fix a wrong entry?
      /ask how do I record last month's tips?
      /ask what does the weekly report include?
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if not context.args:
        await update.message.reply_text(
            "Ask me anything about the bot.\n\n"
            "Examples:\n"
            "  /ask how do I fix a wrong entry?\n"
            "  /ask how do I record tips from last week?\n"
            "  /ask what is the best way to get the weekly report?\n"
            "  /ask how do I import data from before I started using the bot?\n"
            "  /ask what does the inspection report cover?"
        )
        return

    question = " ".join(context.args)
    await update.message.reply_text("Looking that up for you...")

    answer = answer_help_question(question, restaurant["name"])
    await update.message.reply_text(
        f"Q: {question}\n\n"
        f"{answer}\n\n"
        f"Still stuck? /support [describe your problem] to contact the team."
    )


# ── Historical data import ────────────────────────────────────────────────────

async def cmd_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /import [date or range]: [description of what happened]

    Import historical data covering any period — a single day, a fortnight,
    a month, a quarter, or any range. The AI creates the right number of
    dated entries proportional to the period length.

    Format:
      /import [date range]: [description]

    The date range can be anything:
      5 Jan 2025                          — a single day
      6 Jan to 12 Jan 2025               — a week
      1 Jan to 14 Jan 2025               — a fortnight
      January 2025                        — a full month
      Jan to March 2025                   — a quarter
      1 Sept 2024 to 28 Feb 2025         — six months
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if not context.args:
        await update.message.reply_text(
            "Import any period of historical data in plain English.\n\n"
            "Format:\n"
            "  /import [date or range]: [what happened]\n\n"
            "Examples:\n\n"
            "Single day:\n"
            "  /import 5 Jan 2025: Busy Saturday, 94 covers, £3,100.\n"
            "  New lamb dish launched. Bidfood delivery short on salmon.\n\n"
            "Fortnight:\n"
            "  /import 1 Jan to 14 Jan 2025: Quiet post-Christmas period.\n"
            "  Revenue about £28,000, 900 covers. No major issues.\n\n"
            "Month:\n"
            "  /import March 2025: Revenue £72,000, 2,200 covers.\n"
            "  Bidfood prices up 8%. Ahmed left, replaced by Sara.\n"
            "  Kitchen deep clean week 2. Record Saturday on the 22nd.\n\n"
            "Quarter:\n"
            "  /import Oct to Dec 2024: Best quarter ever. Revenue £210,000.\n"
            "  Hired 3 staff. New menu launched November. Fridge replaced Dec.\n\n"
            "Repeat for each period you want to backfill."
        )
        return

    full_text = " ".join(context.args)

    # Split on the first colon to separate date part from description
    if ":" in full_text:
        date_part, description = full_text.split(":", 1)
        date_part = date_part.strip()
        description = description.strip()
    else:
        date_part = full_text
        description = full_text

    if not description:
        await update.message.reply_text(
            "Please include a description after the date.\n\n"
            "Example: /import March 2025: Revenue £72,000, 2,200 covers. Main supplier Bidfood."
        )
        return

    # Parse the date range — supports "X to Y", single dates, month names, etc.
    date_range = None

    if " to " in date_part.lower():
        parts = date_part.lower().split(" to ", 1)
        d1 = _parse_date_range(parts[0].strip())
        d2 = _parse_date_range(parts[1].strip())
        if d1 and d2:
            date_range = (d1[0], d2[1])
    elif "-" in date_part and not any(m in date_part.lower() for m in ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"]):
        # Numeric dash range like "1-14 Jan 2025"
        date_range = _parse_date_range(date_part.strip())
    if not date_range:
        date_range = _parse_date_range(date_part.strip())

    if not date_range:
        await update.message.reply_text(
            f"Couldn't understand the date \"{date_part}\".\n\n"
            "Accepted formats:\n"
            "  5 Jan 2025\n"
            "  6 Jan to 12 Jan 2025\n"
            "  1 Jan to 14 Jan 2025\n"
            "  March 2025\n"
            "  Jan to March 2025\n"
            "  1 Sept 2024 to 28 Feb 2025"
        )
        return

    start_date, end_date = date_range

    # Refuse to import into the future
    if start_date > date.today().isoformat():
        await update.message.reply_text(
            f"The date {_fmt_date(start_date)} is in the future.\n"
            "You can only import historical data."
        )
        return

    # Cap end date at today if it overshoots
    if end_date > date.today().isoformat():
        end_date = date.today().isoformat()

    from datetime import date as _date
    num_days = max(1, (_date.fromisoformat(end_date) - _date.fromisoformat(start_date)).days + 1)

    period_label = _fmt_date(start_date) if start_date == end_date else f"{_fmt_date(start_date)} to {_fmt_date(end_date)}"

    await update.message.reply_text(
        f"Importing {num_days} day(s) of data: {period_label}...\n"
        f"The AI will create proportional entries from your description."
    )

    entries = analyze_history_import(description, start_date, end_date, restaurant["name"])

    if not entries:
        await update.message.reply_text(
            "Could not create entries from that description.\n\n"
            "Try adding more detail — revenue, covers, supplier names, staff issues, equipment problems.\n"
            "Example: /import March 2025: Revenue £72,000, 2,200 covers. Bidfood main supplier. "
            "Fridge broke week 2, repaired same day. Ahmed left 15th. New dessert menu launched."
        )
        return

    staff = _ensure_staff(restaurant["id"], update.effective_user)
    saved = 0
    for e in entries:
        try:
            entry_date = e.get("date", start_date)
            # Clamp to range in case AI strays outside it
            if entry_date < start_date:
                entry_date = start_date
            if entry_date > end_date:
                entry_date = end_date
            entry_time = e.get("time", "12:00:00")
            raw_text = e.get("raw_text", description[:200])
            category = e.get("category", "general")
            structured = json.dumps({
                "category": category,
                "summary": e.get("summary", raw_text[:100]),
                "revenue": e.get("revenue"),
                "covers": e.get("covers"),
                "urgency": e.get("urgency", "low"),
                "action_needed": False,
            })
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO daily_entries
                   (restaurant_id, staff_id, entry_date, entry_time, entry_type,
                    raw_text, structured_data, category)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (restaurant["id"], staff["id"], entry_date, entry_time,
                 "text", raw_text, structured, category),
            )
            conn.commit()
            conn.close()
            saved += 1
        except Exception as ex:
            logger.warning("import: failed to save entry: %s", ex)

    summary_lines = [
        f"  {_fmt_date(e.get('date', start_date))}  [{e.get('category', 'general')}]  {e.get('summary', '')[:65]}"
        for e in entries[:25]  # Cap display at 25 lines
    ]
    if len(entries) > 25:
        summary_lines.append(f"  ... and {len(entries) - 25} more entries")

    await update.message.reply_text(
        f"Imported {saved} entries for {period_label}:\n\n"
        + "\n".join(summary_lines)
        + f"\n\nUse /recall to review any period.\n"
        f"Run /import again for the next period to backfill."
    )


# ── Support ticket system ─────────────────────────────────────────────────────

async def cmd_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /support [message]
    Send a message to the Restaurant-IQ support team.
    They will reply directly in this group when the issue is resolved.

    Examples:
      /support the /correct command is not fixing the entry
      /support we have old data from before we registered — how do we clear it?
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /support [describe your problem]\n\n"
            "Examples:\n"
            "  /support the correction command is not working\n"
            "  /support how do we clear demo data from our account?\n"
            "  /support the weekly report is showing wrong revenue figures\n\n"
            "The support team will reply to this group directly."
        )
        return

    message = " ".join(context.args)
    chat_id = str(update.effective_chat.id)
    ticket_id = save_support_ticket(restaurant["id"], chat_id, message)

    # Forward to owner's chat if configured
    if SUPPORT_CHAT_ID:
        try:
            await update.get_bot().send_message(
                chat_id=SUPPORT_CHAT_ID,
                text=(
                    f"SUPPORT TICKET #{ticket_id}\n"
                    f"Restaurant: {restaurant['name']}\n"
                    f"Chat ID: {chat_id}\n"
                    f"From: {update.effective_user.first_name}\n\n"
                    f"Message:\n{message}\n\n"
                    f"Reply with: /reply {ticket_id} [your response]"
                ),
            )
        except Exception as e:
            logger.warning("Could not forward support ticket to owner: %s", e)

    await update.message.reply_text(
        f"Support ticket #{ticket_id} submitted.\n\n"
        f"The team has been notified and will reply to this group.\n"
        f"You can check the status with /supportstatus\n\n"
        f"For urgent issues, your ticket reference is #{ticket_id}."
    )


async def cmd_supportstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /supportstatus
    Check the status of your support tickets.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    tickets = get_support_tickets(restaurant["id"])

    if not tickets:
        await update.message.reply_text(
            "No support tickets found.\n\n"
            "Use /support [message] to contact the team."
        )
        return

    lines = []
    for t in tickets:
        status_icon = "✅" if t["status"] == "resolved" else "🕐"
        lines.append(f"{status_icon} #{t['id']}  {t['created_at'][:10]}")
        lines.append(f"   {t['message'][:80]}")
        if t["owner_reply"]:
            lines.append(f"   Reply: {t['owner_reply'][:100]}")
        lines.append("")

    await update.message.reply_text(
        f"Support Tickets — {restaurant['name']}\n"
        f"{'─' * 36}\n\n"
        + "\n".join(lines)
    )


async def cmd_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /reply [ticket_id] [message]
    Owner-only: reply to a support ticket. The reply is sent to the restaurant's group.
    Only works when called from the SUPPORT_CHAT_ID.
    """
    if not SUPPORT_CHAT_ID:
        await update.message.reply_text("Support chat ID not configured.")
        return

    caller_chat = str(update.effective_chat.id)
    if caller_chat != str(SUPPORT_CHAT_ID):
        # Silently ignore — don't reveal this command exists to restaurant users
        return

    if not context.args or len(context.args) < 2 or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: /reply [ticket_id] [message]\n"
            "Example: /reply 42 Your data has been cleared — please run /register again."
        )
        return

    ticket_id = int(context.args[0])
    reply_text = " ".join(context.args[1:])

    ticket = get_ticket_by_id(ticket_id)
    if not ticket:
        await update.message.reply_text(f"Ticket #{ticket_id} not found.")
        return

    resolve_support_ticket(ticket_id, reply_text)

    # Send the reply to the restaurant's group
    try:
        await update.get_bot().send_message(
            chat_id=ticket["chat_id"],
            text=(
                f"Support update for ticket #{ticket_id}\n"
                f"{'─' * 30}\n\n"
                f"Your issue: {ticket['message']}\n\n"
                f"Response from the Restaurant-IQ team:\n{reply_text}\n\n"
                f"If this resolves your issue, no further action needed.\n"
                f"If not, use /support to send a follow-up."
            ),
        )
        await update.message.reply_text(f"Reply sent to {ticket['chat_id']} for ticket #{ticket_id}.")
    except Exception as e:
        await update.message.reply_text(f"Could not send reply: {e}")


# ── UK Compliance Commands ────────────────────────────────────────────────────

async def cmd_tips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /tips [period]
    Show tip events logged for a period. Defaults to current month.
    Employment (Allocation of Tips) Act 2023 — restaurants must keep 3-year records.

    Examples:
      /tips               — this month
      /tips last month    — previous calendar month
      /tips March 2026    — specific month
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    query = " ".join(context.args).strip() if context.args else "this month"
    date_range = _parse_date_range(query)

    if not date_range:
        await update.message.reply_text(
            f"Couldn't understand period \"{query}\".\n"
            "Try: this month, last month, March 2026"
        )
        return

    start_date, end_date = date_range
    events = get_tips_for_period(restaurant["id"], start_date, end_date)
    summary = get_tips_summary(restaurant["id"], start_date, end_date)

    period_label = query if start_date == end_date else f"{_fmt_date(start_date)} to {_fmt_date(end_date)}"

    if not events:
        await update.message.reply_text(
            f"Tips Log — {restaurant['name']}\n"
            f"Period: {period_label}\n\n"
            f"No tip events recorded for this period.\n\n"
            f"Tips are logged automatically when your team mentions them in voice notes or messages.\n"
            f"Example: \"Service tonight was great — card tips came to about £180\"\n\n"
            f"Use /tipsreport to generate a compliance record."
        )
        return

    lines = []
    for t in events:
        amount = t["gross_amount"] or 0
        tip_type = (t["tip_type"] or "unknown").upper()
        shift = t["shift"] or "unspecified shift"
        lines.append(f"  {_fmt_date(t['event_date'])}  {tip_type}  £{amount:.2f}  ({shift})")

    events_text = "\n".join(lines)

    await update.message.reply_text(
        f"Tips Log — {restaurant['name']}\n"
        f"Period: {period_label}\n"
        f"{'─' * 40}\n\n"
        f"Card tips:    £{summary['card']:>8,.2f}\n"
        f"Cash tips:    £{summary['cash']:>8,.2f}\n"
        f"Unknown type: £{summary['unknown']:>8,.2f}\n"
        f"{'─' * 40}\n"
        f"Total:        £{summary['total']:>8,.2f}\n\n"
        f"Events ({len(events)}):\n{events_text}\n\n"
        f"Legal requirement: 100% of tips must be passed to staff.\n"
        f"Records must be kept for 3 years (Tips Act 2023).\n"
        f"Use /tipsreport to generate a formal compliance record."
    )


async def cmd_tipsreport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /tipsreport [period]
    Generate a formal Tips Act compliance record for any period.
    Required under Employment (Allocation of Tips) Act 2023.

    Examples:
      /tipsreport            — current month
      /tipsreport last month — previous month
      /tipsreport March 2026 — specific month
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    query = " ".join(context.args).strip() if context.args else "this month"
    date_range = _parse_date_range(query)

    if not date_range:
        await update.message.reply_text(
            f"Couldn't understand period \"{query}\".\n"
            "Try: this month, last month, March 2026"
        )
        return

    start_date, end_date = date_range
    events = get_tips_for_period(restaurant["id"], start_date, end_date)
    summary = get_tips_summary(restaurant["id"], start_date, end_date)

    period_label = f"{_fmt_date(start_date)} to {_fmt_date(end_date)}" if start_date != end_date else _fmt_date(start_date)

    await update.message.reply_text(
        f"Generating Tips Act compliance record for {period_label}...\n"
        f"({len(events)} events, £{summary['total']:.2f} total)"
    )

    events_as_dicts = [dict(e) for e in events]
    report = generate_tips_report(events_as_dicts, summary, restaurant["name"], period_label)

    header = (
        f"TIPS ACT COMPLIANCE RECORD\n"
        f"Employment (Allocation of Tips) Act 2023\n"
        f"{'=' * 38}\n\n"
    )
    full_message = header + report

    if len(full_message) <= 4096:
        await update.message.reply_text(full_message)
    else:
        await update.message.reply_text(full_message[:4000] + "\n\n[Full record — save this message]")

    await update.message.reply_text(
        "This record satisfies your duty to maintain tip allocation records.\n"
        "Keep records for 3 years. Any staff member may request their record at any time.\n\n"
        "To add tips not yet captured: send a voice note or text mentioning the tip amount.\n"
        "Example: \"Last Tuesday card tips were £95 — all passed to staff via Tronc\""
    )


async def cmd_inspection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /inspection
    Generate an FSA Food Hygiene inspection readiness report from the last 90 days of entries.
    Covers: supplier traceability, equipment logs, allergen alerts, staff incidents, compliance gaps.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    today_str = date.today().isoformat()
    cutoff_str = (date.today() - timedelta(days=90)).isoformat()
    entries = get_entries_with_staff(restaurant["id"], cutoff_str, today_str)

    if not entries:
        await update.message.reply_text(
            "No entries found in the last 90 days.\n\n"
            "Inspection readiness requires operational history.\n"
            "Start sending daily voice notes, invoice photos, and shift updates\n"
            "and your inspection record will build automatically."
        )
        return

    await update.message.reply_text(
        f"Generating inspection readiness report from {len(entries)} entries (last 90 days)...\n"
        "Analysing for: supplier traceability, equipment issues, allergen flags, staff records."
    )

    entries_data = []
    for e in entries:
        item = {
            "date": e["entry_date"],
            "time": e["entry_time"],
            "type": e["entry_type"],
            "raw_text": e["raw_text"] or "",
            "category": e["category"],
        }
        if e["structured_data"]:
            try:
                item["analysis"] = json.loads(e["structured_data"])
            except json.JSONDecodeError:
                pass
        entries_data.append(item)

    report = generate_inspection_report(entries_data, restaurant["name"])

    # Also append open allergen alerts
    open_alerts = [a for a in get_allergen_alerts(restaurant["id"], days_back=90) if not a["resolved"]]
    if open_alerts:
        alert_lines = "\n".join(
            f"  #{a['id']} {_fmt_date(a['alert_date'])}  {a['allergen_concern'] or 'Allergen concern'}"
            for a in open_alerts
        )
        report += f"\n\n---\nOpen Allergen Alerts ({len(open_alerts)}):\n{alert_lines}\nResolve with: /resolvallergen [id]"

    header = (
        f"FSA INSPECTION READINESS — {restaurant['name'].upper()}\n"
        f"Based on entries: {_fmt_date(cutoff_str)} to {_fmt_date(today_str)}\n"
        f"{'=' * 38}\n\n"
    )
    full_message = header + report

    if len(full_message) <= 4096:
        await update.message.reply_text(full_message)
    else:
        await update.message.reply_text(full_message[:4000] + "\n\n[Continued — save this report]")
        if len(full_message) > 4000:
            await update.message.reply_text(full_message[4000:8000])


async def cmd_allergens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /allergens
    Show all unresolved allergen alerts from the last 90 days.
    Flagged automatically when supplier changes or ingredient substitutions are detected.
    Natasha's Law requires restaurants to maintain allergen traceability records.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    alerts = get_allergen_alerts(restaurant["id"], days_back=90)
    open_alerts = [a for a in alerts if not a["resolved"]]
    resolved_alerts = [a for a in alerts if a["resolved"]]

    if not alerts:
        await update.message.reply_text(
            f"Allergen Alerts — {restaurant['name']}\n\n"
            "No allergen alerts in the last 90 days.\n\n"
            "Alerts are raised automatically when the AI detects:\n"
            "  - A supplier change or new supplier on an invoice\n"
            "  - An ingredient substitution mentioned in voice notes\n"
            "  - A new product that could affect your allergen declarations\n\n"
            "Natasha's Law: you must keep allergen traceability records and\n"
            "update allergen declarations when ingredients change."
        )
        return

    lines = []
    if open_alerts:
        lines.append(f"OPEN ALERTS ({len(open_alerts)}) — action required:")
        for a in open_alerts:
            supplier = a["supplier_name"] or "unknown supplier"
            concern = a["allergen_concern"] or "Allergen concern — review required"
            lines.append(f"\n  #{a['id']}  {_fmt_date(a['alert_date'])}")
            lines.append(f"  Supplier: {supplier}")
            lines.append(f"  Concern: {concern}")
            lines.append(f"  Resolve: /resolvallergen {a['id']}")

    if resolved_alerts:
        lines.append(f"\n\nRESOLVED ({len(resolved_alerts)}) — kept for traceability record:")
        for a in resolved_alerts:
            lines.append(f"  #{a['id']}  {_fmt_date(a['alert_date'])}  {a['allergen_concern'] or 'Resolved'[:60]}")

    await update.message.reply_text(
        f"Allergen Traceability Log — {restaurant['name']}\n"
        f"Last 90 days\n"
        f"{'─' * 40}\n\n"
        + "\n".join(lines)
        + "\n\n"
        "Natasha's Law: update your allergen declarations whenever\n"
        "a supplier, product, or ingredient changes.\n"
        "Use /inspection for a full inspection readiness report."
    )


async def cmd_resolvallergen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /resolvallergen [id]
    Mark an allergen alert as reviewed and resolved.
    Get IDs from /allergens.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: /resolvallergen [alert id]\n\n"
            "Get alert IDs from /allergens"
        )
        return

    alert_id = int(context.args[0])
    updated = resolve_allergen_alert(alert_id)

    if updated:
        await update.message.reply_text(
            f"Allergen alert #{alert_id} marked as resolved.\n\n"
            "This alert is retained in your traceability record (Natasha's Law).\n"
            "Ensure your allergen declarations have been updated if this involved\n"
            "a supplier or ingredient change."
        )
    else:
        await update.message.reply_text(
            f"Alert #{alert_id} not found. Check the ID with /allergens"
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

    # Message 3b: UK compliance commands
    await update.message.reply_text(
        "UK LEGAL COMPLIANCE COMMANDS\n"
        "══════════════════════════════\n\n"
        "These features are unique to Restaurant-IQ and built specifically\n"
        "for UK legal requirements that every restaurant must meet.\n\n"
        "/import [date range]: [description]\n"
        "  Import any historical period in plain English.\n"
        "  Works for a single day, a fortnight, a month, a quarter, or more.\n"
        "  The AI creates proportional dated entries from your description.\n\n"
        "  A single day:\n"
        "    /import 5 Jan 2025: Busy Saturday, 94 covers, £3,100.\n\n"
        "  A fortnight:\n"
        "    /import 1 Jan to 14 Jan 2025: Quiet period, £28,000 revenue,\n"
        "    900 covers. Bidfood main supplier. No major incidents.\n\n"
        "  A month:\n"
        "    /import March 2025: Revenue £72,000, 2,200 covers.\n"
        "    Bidfood prices up 8%. Ahmed left, Sara started 20th.\n"
        "    Record Saturday on the 22nd — 98 covers.\n\n"
        "  A quarter:\n"
        "    /import Oct to Dec 2024: Revenue £210,000. Hired 3 staff.\n"
        "    New menu in November. Fridge replaced in December.\n\n"
        "  Run /import again for each period. Use /recall to check results.\n\n"
        "/rename [name]\n"
        "  Change the restaurant name without losing any data.\n\n"
        "/cleardata CONFIRM\n"
        "  Delete all entries and start fresh. Registration is kept.\n\n"
        "/tips [period]\n"
        "  Show all tip events logged for a period (default: this month).\n"
        "  Tips are detected automatically from voice notes and messages.\n"
        "  Employment (Allocation of Tips) Act 2023: 100% of tips must go\n"
        "  to staff. Records must be kept for 3 years.\n"
        "  Try: /tips   /tips last month   /tips March 2026\n\n"
        "/tipsreport [period]\n"
        "  Generate a formal Tips Act compliance record.\n"
        "  Any staff member can request this record. Have it ready.\n"
        "  Try: /tipsreport   /tipsreport last month\n\n"
        "/allergens\n"
        "  Allergen traceability log for the last 90 days.\n"
        "  Alerts are raised automatically when the AI detects a supplier\n"
        "  change, ingredient substitution, or new product on an invoice.\n"
        "  Natasha's Law: you must update allergen declarations when\n"
        "  ingredients or suppliers change. Unlimited fines for failures.\n\n"
        "/resolvallergen [id]\n"
        "  Mark an allergen alert as reviewed and resolved.\n"
        "  Resolved alerts remain in your traceability record.\n\n"
        "/inspection\n"
        "  FSA Food Hygiene inspection readiness report.\n"
        "  Analyses your last 90 days of entries and produces a structured\n"
        "  report covering: supplier traceability, equipment logs, temperature\n"
        "  incidents, allergen flags, staff records, and compliance gaps.\n"
        "  EHOs look for exactly this documentation — a 5-star rating\n"
        "  requires evidence of consistent record-keeping.\n"
        "  Run before every inspection or quarterly as a health check."
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


# ── Labour cost command ───────────────────────────────────────────────────────

async def cmd_labour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /labour £450 front of house wages Monday
    /labour £1200 kitchen wages week ending 2 March

    Record labour costs manually. These are included in /financials and the
    weekly report so you get a real net margin figure, not just food GP.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if not context.args:
        await update.message.reply_text(
            "Record wages, agency fees, or any labour cost.\n\n"
            "Usage: /labour £[amount] [description]\n\n"
            "Examples:\n"
            "  /labour £450 front of house wages Monday\n"
            "  /labour £1,200 kitchen wages week ending 2 March\n"
            "  /labour £95 agency cover Saturday lunch\n\n"
            "Labour costs appear in /financials and the weekly report.\n"
            "This gives you real net margin — not just food GP."
        )
        return

    full_text = " ".join(context.args).strip()

    # Parse the amount — accept £1200, £1,200, 1200
    import re as _re
    amount_match = _re_amount.search(full_text)
    if not amount_match:
        await update.message.reply_text(
            "Could not find an amount in your message.\n\n"
            "Usage: /labour £450 front of house wages\n"
            "Include the £ sign or just the number."
        )
        return

    amount_str = amount_match.group(1).replace(",", "")
    try:
        amount = float(amount_str)
    except ValueError:
        await update.message.reply_text("Could not parse the amount. Try: /labour £450 wages Monday")
        return

    description = full_text[amount_match.end():].strip() or "Labour cost"
    today_str = date.today().isoformat()

    save_labour_entry(
        restaurant["id"],
        labour_date=today_str,
        amount=amount,
        description=description,
    )

    await update.message.reply_text(
        f"Labour cost recorded:\n\n"
        f"Amount: £{amount:,.2f}\n"
        f"Description: {description}\n"
        f"Date: {date.today().strftime('%-d %B %Y')}\n\n"
        f"This will appear in /financials and the weekly report.\n"
        f"Use /financials to see your updated net margin."
    )


# ── History command ────────────────────────────────────────────────────────────

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /history         — list the last 4 weekly reports
    /history 2026-03-03 — send the report for that specific week
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if context.args:
        # Try to find a specific report by week start date
        query = " ".join(context.args)
        date_range = _parse_date_range(query)
        if date_range:
            # Snap to Monday of that week
            target = datetime.strptime(date_range[0], "%Y-%m-%d").date()
            week_start = str(target - timedelta(days=target.weekday()))
        else:
            week_start = context.args[0]

        report = get_report_by_week(restaurant["id"], week_start)
        if not report:
            await update.message.reply_text(
                f"No report found for week starting {_fmt_date(week_start)}.\n\n"
                "Use /history to see all saved reports."
            )
            return

        header = (
            f"WEEKLY REPORT — {restaurant['name']}\n"
            f"Week: {_fmt_date(report['week_start'])} to {_fmt_date(report['week_end'])}\n"
            f"{'=' * 34}\n\n"
        )
        full_message = header + (report["report_text"] or "No report text saved.")
        if len(full_message) <= 4096:
            await update.message.reply_text(full_message)
        else:
            await update.message.reply_text(full_message[:4000] + "\n\n[truncated — run /weeklyreport for the current week's full PDF]")
        return

    # No args — list recent reports
    reports = get_weekly_reports(restaurant["id"], limit=4)
    if not reports:
        await update.message.reply_text(
            "No weekly reports saved yet.\n\n"
            "Run /weeklyreport to generate your first one."
        )
        return

    lines = []
    for r in reports:
        lines.append(
            f"  {_fmt_date(r['week_start'])} to {_fmt_date(r['week_end'])}\n"
            f"  → /history {r['week_start']}"
        )

    await update.message.reply_text(
        f"Saved Reports — {restaurant['name']}\n"
        f"{'─' * 36}\n\n"
        + "\n\n".join(lines)
        + "\n\nSend /history [date] to retrieve a specific report.\n"
        "Example: /history last week"
    )


# ── Team stats command ─────────────────────────────────────────────────────────

async def cmd_teamstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /teamstats         — this week
    /teamstats last month — previous month
    Show who's contributing and how much.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    query = " ".join(context.args).strip() if context.args else "this week"
    date_range = _parse_date_range(query)

    if not date_range:
        await update.message.reply_text(
            f"Couldn't understand period \"{query}\".\n"
            "Try: this week, this month, last month"
        )
        return

    start_date, end_date = date_range
    period_label = _fmt_date(start_date) if start_date == end_date else f"{_fmt_date(start_date)} to {_fmt_date(end_date)}"

    stats = get_staff_entry_counts(restaurant["id"], start_date, end_date)

    if not stats:
        await update.message.reply_text("No staff data found.")
        return

    lines = []
    for s in stats:
        count = s["entry_count"] or 0
        last = _fmt_date(s["last_entry_date"]) if s["last_entry_date"] else "never"
        bar = "█" * min(count, 20) if count > 0 else "·"
        role_tag = f" [{s['role']}]" if s["role"] and s["role"] != "staff" else ""
        lines.append(
            f"{s['name']}{role_tag}\n"
            f"  {bar} {count} entries  |  last: {last}"
        )

    total_entries = sum(s["entry_count"] or 0 for s in stats)
    active = sum(1 for s in stats if (s["entry_count"] or 0) > 0)

    await update.message.reply_text(
        f"Team Engagement — {restaurant['name']}\n"
        f"Period: {period_label}\n"
        f"{'─' * 38}\n\n"
        + "\n\n".join(lines)
        + f"\n\n{'─' * 38}\n"
        f"Total entries: {total_entries}  |  Active contributors: {active}/{len(stats)}\n\n"
        "The more your team reports, the sharper the weekly briefing.\n"
        "Best habit: end-of-shift voice note from whoever closes."
    )


# ── 86'd item trend command ────────────────────────────────────────────────────

async def cmd_eightysix(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /eightysix         — this month
    /eightysix last month — previous month
    Shows which menu items run out most frequently — use for ordering and menu decisions.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    query = " ".join(context.args).strip() if context.args else "this month"
    date_range = _parse_date_range(query)

    if not date_range:
        await update.message.reply_text(
            f"Couldn't understand period \"{query}\".\n"
            "Try: this month, last month, this week"
        )
        return

    start_date, end_date = date_range
    period_label = _fmt_date(start_date) if start_date == end_date else f"{_fmt_date(start_date)} to {_fmt_date(end_date)}"

    trends = get_eightysix_trends(restaurant["id"], start_date, end_date)

    if not trends:
        await update.message.reply_text(
            f"No 86'd items recorded for {period_label}.\n\n"
            "Items are logged automatically when your team mentions running out of something.\n"
            "Example voice note: \"We 86'd the salmon at 7pm, ran out of the lamb too.\""
        )
        return

    lines = []
    for item, count in trends[:15]:
        bar = "█" * min(count, 10)
        lines.append(f"  {bar} {count}×  {item.title()}")

    await update.message.reply_text(
        f"86'd Items — {restaurant['name']}\n"
        f"Period: {period_label}\n"
        f"{'─' * 36}\n\n"
        + "\n".join(lines)
        + f"\n\nTotal unique items: {len(trends)}\n\n"
        "Use this for:\n"
        "  - Ordering: increase PAR for frequently 86'd items\n"
        "  - Menu: consider removing or reducing portion sizes on items that always run out\n"
        "  - Pricing: popular items that 86 early may support a price increase"
    )


# ── Export CSV command ─────────────────────────────────────────────────────────

async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /export           — export this week's entries as CSV
    /export last month — export a specific period
    Useful for importing into Excel, accounting software, or sharing with accountants.
    """
    import csv
    import io

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
    entries = get_entries_with_staff(restaurant["id"], start_date, end_date)

    if not entries:
        await update.message.reply_text(
            f"No entries found for {_fmt_date(start_date)} to {_fmt_date(end_date)}."
        )
        return

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Time", "Type", "Staff", "Category", "Summary", "Raw Text", "Urgency", "Revenue", "Covers"])

    for e in entries:
        summary = ""
        urgency = ""
        revenue = ""
        covers = ""
        if e["structured_data"]:
            try:
                a = json.loads(e["structured_data"])
                summary = a.get("summary", "")
                urgency = a.get("urgency", "")
                revenue = a.get("revenue") or ""
                covers = a.get("covers") or ""
            except (json.JSONDecodeError, TypeError):
                pass

        writer.writerow([
            e["entry_date"],
            e["entry_time"],
            e["entry_type"],
            e["staff_name"] or "",
            e["category"] or "",
            summary,
            (e["raw_text"] or "")[:300],
            urgency,
            revenue,
            covers,
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")  # utf-8-sig for Excel compatibility
    period_label = f"{start_date}_to_{end_date}"
    safe_name = restaurant["name"].replace(" ", "_").replace("/", "-")
    filename = f"{safe_name}_{period_label}.csv"

    await update.message.reply_document(
        document=csv_bytes,
        filename=filename,
        caption=(
            f"Data export: {restaurant['name']}\n"
            f"{_fmt_date(start_date)} to {_fmt_date(end_date)}\n"
            f"{len(entries)} entries"
        ),
    )


# ── GDPR data deletion command ─────────────────────────────────────────────────

async def cmd_deletedata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /deletedata 90     — delete all entries older than 90 days
    /deletedata 365    — delete entries older than 1 year
    GDPR compliance: personal data should not be kept longer than necessary.
    3-year retention applies to Tips Act records (those are NOT deleted by this command).
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if not context.args:
        await update.message.reply_text(
            "Delete entries older than a specified number of days.\n\n"
            "Usage: /deletedata [days]\n\n"
            "Examples:\n"
            "  /deletedata 90   — delete entries older than 90 days\n"
            "  /deletedata 365  — delete entries older than 1 year\n\n"
            "GDPR note: this deletes daily_entries and linked compliance records.\n"
            "Tips Act records (3-year legal retention) are NOT affected.\n"
            "Use /cleardata CONFIRM to delete everything."
        )
        return

    if not context.args[0].isdigit():
        await update.message.reply_text(
            "Please specify the number of days.\n"
            "Example: /deletedata 90"
        )
        return

    days = int(context.args[0])
    if days < 30:
        await update.message.reply_text(
            "Minimum retention period is 30 days.\n"
            "Example: /deletedata 90"
        )
        return

    deleted = delete_entries_older_than(restaurant["id"], days)

    if deleted == 0:
        await update.message.reply_text(
            f"No entries older than {days} days found. Nothing deleted."
        )
        return

    await update.message.reply_text(
        f"GDPR data deletion complete.\n\n"
        f"Deleted: {deleted} entries older than {days} days\n"
        f"Restaurant: {restaurant['name']}\n\n"
        f"Remaining entries and compliance records are intact.\n"
        f"Tips Act records are unaffected (3-year legal retention applies)."
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
        entry_id = save_entry(
            restaurant["id"],
            staff["id"],
            "voice",
            text,
            json.dumps(analysis),
            analysis.get("category", "general"),
        )
        _auto_log_compliance(restaurant["id"], entry_id, analysis, date.today().isoformat())

        urgency = analysis.get("urgency", "low")
        icon = URGENCY_ICONS.get(urgency, "⚪")
        summary = analysis.get("summary", text[:100])

        compliance_note = ""
        if analysis.get("tips_detected"):
            compliance_note += "\n\nTips Act: tip event logged automatically."
        if analysis.get("allergen_risk"):
            compliance_note += "\n\nAllergen alert: possible allergen impact flagged. Use /allergens to review."

        await update.message.reply_text(
            f"Captured ({update.effective_user.first_name}):\n"
            f'"{text[:200]}"\n\n'
            f"Category: {analysis.get('category', 'general')}\n"
            f"Summary: {summary}\n"
            f"Urgency: {icon} {urgency}"
            f"{compliance_note}\n\n"
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
        invoice_id = None
        price_alerts = []
        if analysis.get("total_amount") and analysis.get("total_amount", 0) > 0:
            due_date = analysis.get("due_date") or _default_due_date(
                analysis.get("date"), analysis.get("payment_terms")
            )
            invoice_id = save_invoice(
                restaurant["id"],
                entry_id,
                analysis.get("supplier_name", "Unknown"),
                analysis.get("date", str(date.today())),
                due_date,
                analysis.get("total_amount", 0),
                analysis.get("vat", 0),
                analysis.get("summary", ""),
            )

            # Save line items for price trend tracking
            line_items = analysis.get("items") or []
            supplier = analysis.get("supplier_name", "Unknown")
            recorded_date = analysis.get("date") or str(date.today())
            if line_items and invoice_id:
                price_alerts = detect_price_changes(
                    restaurant["id"], supplier, line_items, recorded_date
                )
                save_invoice_line_items(
                    restaurant["id"], invoice_id, supplier, line_items, recorded_date
                )

        _auto_log_compliance(restaurant["id"], entry_id, analysis, date.today().isoformat())

        supplier = analysis.get("supplier_name") or "Unknown"
        total = analysis.get("total_amount")
        total_str = f"£{total:.2f}" if total else "Not found"
        raw_due = analysis.get("due_date")
        due_str = f"\nPayment due: {_fmt_date(raw_due) if raw_due else 'defaulting to 30 days'}" if total else ""

        allergen_note = ""
        if analysis.get("allergen_risk"):
            allergen_note = f"\n\nAllergen alert: {analysis.get('allergen_detail', 'Possible allergen impact — check your declarations.')}\nUse /allergens to review all flagged items."

        price_alert_note = ""
        if price_alerts:
            lines = []
            for pa in price_alerts:
                direction = "▲" if pa["pct_change"] > 0 else "▼"
                lines.append(
                    f"  {direction} {pa['item']}: £{pa['old_avg']} → £{pa['new_price']} "
                    f"({pa['pct_change']:+.1f}%)"
                )
            price_alert_note = "\n\n⚠️ Price changes vs. your history:\n" + "\n".join(lines)

        await update.message.reply_text(
            f"Invoice / Receipt Captured:\n"
            f"Supplier: {supplier}\n"
            f"Total: {total_str}{due_str}\n"
            f"Summary: {analysis.get('summary', 'Document logged')}"
            f"{allergen_note}"
            f"{price_alert_note}\n\n"
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
    entry_id = save_entry(
        restaurant["id"],
        staff["id"],
        "text",
        text,
        json.dumps(analysis),
        analysis.get("category", "general"),
    )
    _auto_log_compliance(restaurant["id"], entry_id, analysis, date.today().isoformat())

    urgency = analysis.get("urgency", "low")
    icon = URGENCY_ICONS.get(urgency, "⚪")
    summary = analysis.get("summary", text[:80])

    compliance_note = ""
    if analysis.get("tips_detected"):
        compliance_note += "\n\nTips Act: tip event logged automatically."
    if analysis.get("allergen_risk"):
        compliance_note += "\n\nAllergen alert: possible allergen impact flagged. Use /allergens to review."

    await update.message.reply_text(
        f"Captured ({update.effective_user.first_name}):\n"
        f'"{text[:200]}"\n\n'
        f"Category: {analysis.get('category', 'general')}\n"
        f"Summary: {summary}\n"
        f"Urgency: {icon} {urgency}"
        f"{compliance_note}\n\n"
        f"Wrong detail? /correct the beef was £450 not £540\nWrong entry? /deletelast and re-send."
    )


# ── Scheduled jobs ────────────────────────────────────────────────────────────

async def _auto_weekly_report_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Runs every Monday at 08:00.
    Auto-generates and sends the weekly report to every registered restaurant group.
    Owners no longer need to remember /weeklyreport — it arrives automatically.
    """
    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    week_end = today.strftime("%Y-%m-%d")

    restaurants = get_all_restaurants()
    logger.info("Auto weekly report job: %d restaurants", len(restaurants))

    for restaurant in restaurants:
        chat_id = restaurant["telegram_group_id"]
        if not chat_id:
            continue

        try:
            from database import get_entries_for_period
            entries = get_entries_for_period(restaurant["id"], week_start, week_end)
            if not entries:
                logger.info("Auto report: no entries for %s — skipping", restaurant["name"])
                continue

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

            safe_name = restaurant["name"].replace(" ", "_").replace("/", "-")
            pdf_path = os.path.join(REPORTS_DIR, f"{safe_name}_{week_start}.pdf")
            generate_pdf_report(report_text, restaurant["name"], week_start, week_end, pdf_path)

            header = f"RESTAURANT-IQ WEEKLY BRIEFING\n{'=' * 34}\n\n"
            full_message = header + report_text
            if len(full_message) <= 4096:
                await context.bot.send_message(chat_id=chat_id, text=full_message)
            else:
                await context.bot.send_message(chat_id=chat_id, text=full_message[:4000] + "\n\n[continued in PDF...]")

            with open(pdf_path, "rb") as pdf_file:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=pdf_file,
                    filename=os.path.basename(pdf_path),
                    caption=f"Weekly briefing for {restaurant['name']} — {_fmt_date(week_start)}",
                )

            logger.info("Auto report sent to %s (%s)", restaurant["name"], chat_id)

        except Exception as e:
            logger.error("Auto report failed for %s: %s", restaurant.get("name", "?"), e)


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

    # CRITICAL SAFETY CHECK: refuse if a real restaurant is already registered.
    # Without this, demo data gets injected directly into the live restaurant.
    existing = get_restaurant_by_group(chat_id)
    if existing and existing["name"] != DEMO_RESTAURANT_NAME:
        await update.message.reply_text(
            f"This group is already registered as '{existing['name']}'\n\n"
            f"Loading demo data here would mix fake data with your real records.\n\n"
            f"To try the demo safely:\n"
            f"  1. Create a new Telegram group\n"
            f"  2. Add the bot to that group\n"
            f"  3. Run /demo there\n\n"
            f"Your real data in this group is untouched."
        )
        return

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

    # Data management
    app.add_handler(CommandHandler("rename", cmd_rename))
    app.add_handler(CommandHandler("cleardata", cmd_cleardata))

    # Help & onboarding
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("import", cmd_import))

    # Support ticket system
    app.add_handler(CommandHandler("support", cmd_support))
    app.add_handler(CommandHandler("supportstatus", cmd_supportstatus))
    app.add_handler(CommandHandler("reply", cmd_reply))

    # UK compliance commands
    app.add_handler(CommandHandler("tips", cmd_tips))
    app.add_handler(CommandHandler("tipsreport", cmd_tipsreport))
    app.add_handler(CommandHandler("inspection", cmd_inspection))
    app.add_handler(CommandHandler("allergens", cmd_allergens))
    app.add_handler(CommandHandler("resolvallergen", cmd_resolvallergen))

    # New features
    app.add_handler(CommandHandler("labour", cmd_labour))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("teamstats", cmd_teamstats))
    app.add_handler(CommandHandler("eightysix", cmd_eightysix))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("deletedata", cmd_deletedata))

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

    # Auto weekly report every Monday at 08:00 (owners don't need to run /weeklyreport)
    app.job_queue.run_daily(
        _auto_weekly_report_job,
        time=datetime.strptime("08:00", "%H:%M").time(),
        days=(0,),  # 0 = Monday
        name="weekly_reports",
    )

    logger.info("Restaurant-IQ Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
