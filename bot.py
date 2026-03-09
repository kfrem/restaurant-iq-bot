"""
TradeFlow Telegram Bot
--------------------------
Entry point. Run with:  python bot.py

Handles:
  - /start              — welcome message
  - /register           — register this Telegram group as a restaurant
  - /status             — show entries captured this week
  - /weeklyreport       — generate and send the weekly intelligence briefing
  - /recall [date]      — recall what was recorded on a specific date or period
  - /financials         — P&L and cashflow summary for any period
  - /groupreport        — consolidated P&L across all registered sites (multi-site owners)
  - /outstanding        — list all unpaid invoices with due dates
  - /markpaid [id]      — mark an invoice as paid
  - /demo               — load a realistic week of demo data for client presentations
  - /demoreset          — remove all demo data from this chat

UK Legal Compliance (unique to TradeFlow):
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
import subprocess
import urllib.request as _urllib_req
import json as _json_mod
from datetime import timezone as _tz
from datetime import datetime, timedelta, date

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import TELEGRAM_BOT_TOKEN, SUPPORT_CHAT_ID, DEFAULT_CURRENCY_CODE, DEFAULT_CURRENCY_SYMBOL
from dashboard import start_dashboard_server
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
    get_invoices_for_period,
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
    update_restaurant_profile,
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
    set_stock_par,
    update_stock_count,
    get_stock_status,
    get_low_stock_items,
    delete_stock_item,
    add_rota_shift,
    get_rota_for_week,
    delete_rota_shift,
    copy_rota_week,
    clear_rota_week,
    get_or_create_dashboard_token,
    get_restaurant_currency,
    set_restaurant_currency,
    SUPPORTED_CURRENCIES,
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

# Regex to extract monetary amounts like £450, $450, ₦450, 1200, 1200.50
_re_amount = re.compile(r"[£$€₦R]?([\d,]+(?:\.\d{1,2})?)")


def _cs(restaurant) -> str:
    """Return the currency symbol for this restaurant (e.g. £, $, ₦).
    Works with both sqlite3.Row objects and plain dicts."""
    if restaurant is None:
        return DEFAULT_CURRENCY_SYMBOL
    try:
        sym = restaurant["currency_symbol"]
        return sym if sym else DEFAULT_CURRENCY_SYMBOL
    except (KeyError, TypeError, IndexError):
        return DEFAULT_CURRENCY_SYMBOL

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
        "Welcome to TradeFlow!\n\n"
        "I capture operational data from your team and turn it into weekly intelligence briefings.\n\n"
        "SETUP:\n"
        "  /register YourBusinessName — Register this group\n"
        "  /currency USD              — Set your currency (GBP, USD, NGN, KES, ZAR, GHS...)\n\n"
        "DAILY USE (just send me):\n"
        "  Voice note — Shift update, observations, issues\n"
        "  Photo       — Invoice, receipt, delivery note\n"
        "  Text        — Any quick update\n\n"
        "REPORTS & QUERIES:\n"
        "  /weeklyreport          — Full weekly briefing + P&L (PDF included)\n"
        "  /history               — Browse past weekly reports\n"
        "  /today                 — Everything logged today\n"
        "  /financials            — Revenue, costs, labour and net margin\n"
        "  /groupreport           — Consolidated P&L across ALL your sites\n"
        "  /stock                 — Stock levels vs par (all items)\n"
        "  /stock low             — Only items below par level\n"
        "  /stock set item 10 kg  — Set par level for an item\n"
        "  /stock count item 3 kg — Log current stock count\n"
        "  /rota                  — Show this week's staff rota\n"
        "  /rota add Mon John 9am-5pm — Add a shift to the rota\n"
        "  /rota copy             — Copy last week's rota to this week\n"
        "  /rota next             — View next week's rota\n"
        "  /dashboard             — Get your private live web dashboard link\n"
        "  /recall 5 May          — What happened on a specific date\n"
        "  /recall last week      — Summary of last week\n"
        "  /recall March          — Everything recorded in March\n"
        "  /status                — Entries captured this week\n\n"
        "COSTS & LABOUR:\n"
        "  /labour 450 wages Mon  — Record wages or labour costs\n"
        "  /outstanding           — List unpaid invoices\n"
        "  /markpaid 12           — Mark invoice #12 as paid\n\n"
        "TEAM & MENU:\n"
        "  /teamstats             — Who's contributing and how much\n"
        "  /eightysix             — Most frequently 86'd items\n\n"
        "COMPLIANCE (Restaurant Pack):\n"
        "  /tips                  — Tips log (Tips Act 2023)\n"
        "  /tipsreport            — Formal tip allocation record\n"
        "  /allergens             — Allergen traceability log (Natasha's Law)\n"
        "  /inspection            — FSA inspection readiness report\n\n"
        "DATA MANAGEMENT:\n"
        "  /rename NewName        — Rename your business\n"
        "  /import [dates]: [description] — Import any historical period\n"
        "  /export                — Export entries as CSV (Excel/accountants)\n"
        "  /export xero           — Xero Bills import CSV (purchase invoices)\n"
        "  /export sage           — Sage 50 purchase journal CSV\n"
        "  /export payroll        — Labour cost sheet (BrightPay/Sage Payroll)\n"
        "  /deletedata 90         — Delete entries older than 90 days (GDPR)\n"
        "  /cleardata CONFIRM     — Delete all entries and start fresh\n\n"
        "HELP & SUPPORT:\n"
        "  /ask [question]        — AI-powered help\n"
        "  /support [message]     — Contact the support team\n"
        "  /supportstatus         — Check your support tickets\n\n"
        "Every message from any team member in this group is captured and analysed.\n"
        "Weekly reports are sent automatically every Monday at 08:00.\n\n"
        "Type /features for a full guide, or /ask [your question] for instant help."
    )


# ── Registration conversation states ──────────────────────────────────────────
REG_NAME, REG_LOCATION, REG_CONTACT, REG_LEGAL, REG_BUSINESS = range(5)

_SKIP_HINT = "Reply with the details, or type *skip* to move on."
_DONE_WORDS = {"skip", "done", "next", "no", "n", "/skip", "/done"}


def _is_skip(text: str) -> bool:
    return text.strip().lower() in _DONE_WORDS


async def cmd_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for /register — starts the onboarding wizard."""
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    existing = get_restaurant_by_group(chat_id)

    # Already registered — offer to update profile or just rename
    if existing:
        name_given = " ".join(context.args) if context.args else ""
        if name_given and name_given != existing["name"]:
            update_restaurant_name(chat_id, name_given)
            register_staff(existing["id"], user_id, update.effective_user.first_name or "Owner", "owner")
            await update.message.reply_text(
                f"Name updated to: *{name_given}*\n\n"
                f"All existing data is preserved.\n"
                f"Use /status to check your data.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"*{existing['name']}* is already registered.\n\n"
                f"Use /rename to change the name.\n"
                f"Use /profile to update your company details.",
                parse_mode="Markdown",
            )
        return ConversationHandler.END

    # New registration — if name was given inline, skip straight to profile
    if context.args:
        name = " ".join(context.args)
        _do_register(name, chat_id, user_id, update.effective_user.first_name)
        context.user_data["reg_chat_id"] = chat_id
        await update.message.reply_text(
            f"*{name}* is now registered and TradeFlow is live!\n\n"
            f"Team members can start sending voice notes, photos and texts right away.\n\n"
            f"Tip: run /currency to set your local currency (default: GBP).\n\n"
            f"─────────────────────\n"
            f"*Optional: Complete your company profile*\n"
            f"Adding your details means they appear on every report.\n\n"
            f"*Step 1 of 4 — Location*\n"
            f"What is your address? Include street, city and postcode.\n\n"
            f"{_SKIP_HINT}",
            parse_mode="Markdown",
        )
        return REG_LOCATION

    # No name given — ask for it
    await update.message.reply_text(
        "*Welcome to TradeFlow!*\n\n"
        "Let's get you set up. This takes about 2 minutes.\n"
        "You can skip any optional step.\n\n"
        "*What is your business trading name?*",
        parse_mode="Markdown",
    )
    context.user_data["reg_chat_id"] = chat_id
    context.user_data["reg_user_id"] = user_id
    return REG_NAME


def _do_register(name: str, chat_id: str, user_id: str, first_name: str):
    register_restaurant(name, chat_id, user_id)
    restaurant = get_restaurant_by_group(chat_id)
    if restaurant:
        register_staff(restaurant["id"], user_id, first_name or "Owner", "owner")


async def _reg_got_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if not name or name.startswith("/"):
        await update.message.reply_text("Please enter a name for your restaurant.")
        return REG_NAME

    chat_id = context.user_data.get("reg_chat_id", str(update.effective_chat.id))
    user_id = str(update.effective_user.id)
    _do_register(name, chat_id, user_id, update.effective_user.first_name)

    await update.message.reply_text(
        f"*{name}* is now registered and TradeFlow is live!\n\n"
        f"Team members can start sending voice notes, photos and texts right away.\n\n"
        f"Tip: run /currency to set your local currency (default: GBP).\n\n"
        f"─────────────────────\n"
        f"*Optional: Complete your company profile*\n"
        f"Adding details means they appear on every report.\n\n"
        f"*Step 1 of 4 — Location*\n"
        f"What is your address? Include street, city and postcode.\n\n"
        f"{_SKIP_HINT}",
        parse_mode="Markdown",
    )
    return REG_LOCATION


async def _reg_got_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.user_data.get("reg_chat_id", str(update.effective_chat.id))
    text = update.message.text.strip()

    if not _is_skip(text):
        # Try to parse city and postcode from free text
        # UK postcode pattern
        import re as _re
        postcode_match = _re.search(r'\b[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2}\b', text, _re.I)
        postcode = postcode_match.group(0).upper() if postcode_match else None
        address = text
        update_restaurant_profile(chat_id, address=address, postcode=postcode)

    await update.message.reply_text(
        f"*Step 2 of 4 — Contact Details*\n"
        f"Phone number and/or email address?\n"
        f"_(e.g. 020 7123 4567 | hello@yourbistro.com)_\n\n"
        f"{_SKIP_HINT}",
        parse_mode="Markdown",
    )
    return REG_CONTACT


async def _reg_got_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.user_data.get("reg_chat_id", str(update.effective_chat.id))
    text = update.message.text.strip()

    if not _is_skip(text):
        import re as _re
        email_match = _re.search(r'[\w.+-]+@[\w-]+\.[a-z]{2,}', text, _re.I)
        phone_match = _re.search(r'[\d\s\+\(\)-]{7,}', text)
        email = email_match.group(0) if email_match else None
        # Remove email from phone search area
        phone_text = text.replace(email, "") if email else text
        phone_match2 = _re.search(r'[\d\s\+\(\)-]{7,}', phone_text)
        phone = phone_match2.group(0).strip() if phone_match2 else None
        update_restaurant_profile(chat_id, email=email, phone=phone)

    await update.message.reply_text(
        f"*Step 3 of 4 — Legal & Tax*\n"
        f"Company registration number and/or VAT number?\n"
        f"_(e.g. 12345678 | GB123456789)_\n\n"
        f"{_SKIP_HINT}",
        parse_mode="Markdown",
    )
    return REG_LEGAL


async def _reg_got_legal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.user_data.get("reg_chat_id", str(update.effective_chat.id))
    text = update.message.text.strip()

    if not _is_skip(text):
        import re as _re
        vat_match = _re.search(r'GB\s*\d{9}|\d{9}', text, _re.I)
        # Company number is typically 8 digits (UK)
        co_match = _re.search(r'\b\d{8}\b', text)
        vat = vat_match.group(0).upper() if vat_match else None
        company_number = co_match.group(0) if co_match else text if not vat else None
        update_restaurant_profile(chat_id, vat_number=vat, company_number=company_number)

    await update.message.reply_text(
        f"*Step 4 of 4 — About the Business*\n"
        f"Cuisine type, number of covers and number of locations?\n"
        f"_(e.g. Italian, 60 covers, 3 locations)_\n\n"
        f"{_SKIP_HINT}",
        parse_mode="Markdown",
    )
    return REG_BUSINESS


async def _reg_got_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.user_data.get("reg_chat_id", str(update.effective_chat.id))
    text = update.message.text.strip()

    if not _is_skip(text):
        import re as _re
        covers_match = _re.search(r'(\d+)\s*covers?', text, _re.I)
        branches_match = _re.search(r'(\d+)\s*(location|branch|site|outlet)s?', text, _re.I)
        num_covers = int(covers_match.group(1)) if covers_match else None
        num_branches = int(branches_match.group(1)) if branches_match else None
        # Cuisine: first word(s) before any number
        cuisine_match = _re.match(r'^([A-Za-z\s&/-]+?)(?:\s*,|\s*\d|$)', text)
        cuisine = cuisine_match.group(1).strip() if cuisine_match else None
        update_restaurant_profile(
            chat_id,
            cuisine_type=cuisine,
            num_covers=num_covers,
            num_branches=num_branches,
            profile_complete=1,
        )

    restaurant = get_restaurant_by_group(chat_id)
    name = restaurant["name"] if restaurant else "Your restaurant"

    # Build a summary of what was saved
    lines = []
    if restaurant:
        fields = {
            "Address": restaurant["address"],
            "Phone": restaurant["phone"],
            "Email": restaurant["email"],
            "Company No": restaurant["company_number"],
            "VAT No": restaurant["vat_number"],
            "Cuisine": restaurant["cuisine_type"],
            "Covers": restaurant["num_covers"],
            "Locations": restaurant["num_branches"],
        }
        for label, val in fields.items():
            if val:
                lines.append(f"  {label}: {val}")

    profile_summary = "\n".join(lines) if lines else "  (no optional details saved)"

    await update.message.reply_text(
        f"*All set! {name} is fully registered.*\n\n"
        f"*Profile saved:*\n{profile_summary}\n\n"
        f"You can update any of these later with /profile\n\n"
        f"*What to do next:*\n"
        f"  • Send a voice note about today's shift\n"
        f"  • Send a photo of an invoice\n"
        f"  • Type /features to see everything TradeFlow can do",
        parse_mode="Markdown",
    )
    context.user_data.clear()
    return ConversationHandler.END


async def _reg_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.user_data.get("reg_chat_id", str(update.effective_chat.id))
    restaurant = get_restaurant_by_group(chat_id)
    if restaurant:
        await update.message.reply_text(
            f"Profile setup cancelled. *{restaurant['name']}* is still registered and ready to use.\n"
            f"Run /profile any time to add your company details.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("Registration cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


async def cmd_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/profile — update company details for an already-registered restaurant."""
    chat_id = str(update.effective_chat.id)
    restaurant = get_restaurant_by_group(chat_id)
    if not restaurant:
        await update.message.reply_text(
            "Not registered yet. Use /register to get started."
        )
        return ConversationHandler.END

    context.user_data["reg_chat_id"] = chat_id
    await update.message.reply_text(
        f"*Updating profile for {restaurant['name']}*\n\n"
        f"*Step 1 of 4 — Location*\n"
        f"What is your address? Include street, city and postcode.\n\n"
        f"{_SKIP_HINT}",
        parse_mode="Markdown",
    )
    return REG_LOCATION


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
        f"TradeFlow — {restaurant['name']}\n"
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

    report_text = generate_weekly_report(entries_data, restaurant["name"], financials, _cs(restaurant))

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
    sym = _cs(restaurant)
    cost_lines = ""
    if fin["cost_items"]:
        cost_lines = "\nInvoices captured:\n" + "\n".join(
            f"  {item['date']}  {item['supplier']:.<30} {sym}{item['amount']:>8,.2f}"
            for item in fin["cost_items"]
        )

    labour_lines = ""
    if fin.get("labour_items"):
        labour_lines = "\nLabour recorded:\n" + "\n".join(
            f"  {item['date']}  {(item['description'] or 'Labour'):.<30} {sym}{item['amount']:>8,.2f}"
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
        f"\nOutstanding invoices (unpaid): {len(outstanding)} totalling {sym}{outstanding_total:,.2f}"
        if outstanding else "\nAll captured invoices: paid ✅"
    )

    labour_note = (
        f"\nLabour costs:            {sym}{fin['labour_total']:>10,.2f}"
        if fin.get("labour_total", 0) > 0
        else "\nLabour costs:               not recorded — use /labour to add"
    )

    await update.message.reply_text(
        f"Financial Summary — {restaurant['name']}\n"
        f"Period: {period_label}\n"
        f"{'─' * 40}\n\n"
        f"Revenue captured:        {sym}{fin['revenue_total']:>10,.2f}\n"
        f"Invoiced costs captured: {sym}{fin['cost_total']:>10,.2f}\n"
        f"{labour_note}\n"
        f"{'─' * 40}\n"
        f"Net profit:              {sym}{fin['gross_profit']:>10,.2f}\n"
        f"Food GP margin:          {food_margin:>9.1f}%\n"
        f"Net margin (inc labour): {net_margin:>9.1f}%\n"
        f"{margin_note}"
        f"{outstanding_line}"
        f"{cost_lines}"
        f"{labour_lines}\n\n"
        f"Note: revenue = reported takings. Costs = photographed invoices.\n"
        f"Labour = entries via /labour. Use /labour £X [description] to record wages."
    )


async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /stock                        — show all stock levels vs par
    /stock low                    — show only items below par
    /stock set chicken 10 kg      — set par level for an item
    /stock count chicken 3 kg     — record current stock count
    /stock remove chicken         — remove an item from the list

    Examples:
      /stock set beef mince 5 kg
      /stock set milk 12 litres
      /stock count beef mince 2 kg
      /stock low
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    args = list(context.args) if context.args else []
    rid = restaurant["id"]

    def _parse_item_amount(tokens):
        """
        Parse 'chicken 3 kg' or 'chicken 3kg' or 'beef mince 2.5 kg'
        into (item_name, amount, unit).
        Handles multi-word item names by treating the last numeric token
        (plus optional trailing unit) as the amount.
        """
        if not tokens:
            return None, None, ""
        # Walk backwards to find the first numeric token
        unit = ""
        amount = None
        name_end = len(tokens)
        for i in range(len(tokens) - 1, -1, -1):
            tok = tokens[i]
            # Strip trailing unit letters from the token e.g. "3kg" → "3"
            num_part = tok.rstrip("abcdefghijklmnopqrstuvwxyz")
            unit_part = tok[len(num_part):]
            try:
                amount = float(num_part)
                if unit_part:
                    unit = unit_part
                elif i + 1 < len(tokens):
                    # next token might be the unit if it's purely alphabetic
                    next_tok = tokens[i + 1]
                    if next_tok.isalpha() and not _is_numeric(next_tok):
                        unit = next_tok
                        name_end = i
                    else:
                        name_end = i
                else:
                    name_end = i
                break
            except ValueError:
                continue
        if amount is None:
            return " ".join(tokens), None, ""
        item_name = " ".join(tokens[:name_end])
        return item_name.strip(), amount, unit.strip()

    def _is_numeric(s):
        try:
            float(s)
            return True
        except ValueError:
            return False

    subcommand = args[0].lower() if args else "status"

    # ── /stock set <item> <amount> [unit] ─────────────────────────────────────
    if subcommand == "set":
        item_name, par_level, unit = _parse_item_amount(args[1:])
        if not item_name or par_level is None:
            await update.message.reply_text(
                "Usage: /stock set chicken 10 kg\n"
                "Multi-word: /stock set beef mince 5 kg"
            )
            return
        set_stock_par(rid, item_name, par_level, unit)
        unit_str = f" {unit}" if unit else ""
        await update.message.reply_text(
            f"Par level set: {item_name.title()} — {par_level:g}{unit_str}\n\n"
            f"Now log counts with: /stock count {item_name} <amount>{unit_str}"
        )

    # ── /stock count <item> <amount> [unit] ───────────────────────────────────
    elif subcommand in ("count", "update"):
        item_name, current_level, unit = _parse_item_amount(args[1:])
        if not item_name or current_level is None:
            await update.message.reply_text(
                "Usage: /stock count chicken 3 kg\n"
                "Item must have a par level set first: /stock set chicken 10 kg"
            )
            return
        updated = update_stock_count(rid, item_name, current_level)
        if not updated:
            # Item not found — offer to create it
            await update.message.reply_text(
                f"'{item_name}' not found in your stock list.\n"
                f"Set a par level first: /stock set {item_name} <par_amount>"
            )
            return
        # Fetch the item to check against par
        items = get_stock_status(rid)
        item = next((i for i in items if i["item_name"] == item_name.lower().strip()), None)
        unit_str = f" {item['unit']}" if item and item["unit"] else ""
        par = item["par_level"] if item else 0
        if current_level < par:
            deficit = par - current_level
            await update.message.reply_text(
                f"Stock updated: {item_name.title()} — {current_level:g}{unit_str}\n"
                f"⚠️ BELOW PAR — need {deficit:g}{unit_str} more (par: {par:g}{unit_str})"
            )
        else:
            surplus = current_level - par
            await update.message.reply_text(
                f"Stock updated: {item_name.title()} — {current_level:g}{unit_str} ✅\n"
                f"Above par by {surplus:g}{unit_str} (par: {par:g}{unit_str})"
            )

    # ── /stock remove <item> ──────────────────────────────────────────────────
    elif subcommand == "remove":
        item_name = " ".join(args[1:]).strip()
        if not item_name:
            await update.message.reply_text("Usage: /stock remove chicken")
            return
        deleted = delete_stock_item(rid, item_name)
        if deleted:
            await update.message.reply_text(f"Removed '{item_name}' from stock list.")
        else:
            await update.message.reply_text(f"'{item_name}' not found in your stock list.")

    # ── /stock low ────────────────────────────────────────────────────────────
    elif subcommand == "low":
        low_items = get_low_stock_items(rid)
        if not low_items:
            await update.message.reply_text(
                "No items below par level. All stock looks good. ✅\n\n"
                "Note: items without a count recorded will not appear here.\n"
                "Log counts with: /stock count <item> <amount>"
            )
            return
        lines = []
        for item in low_items:
            unit_str = f" {item['unit']}" if item["unit"] else ""
            deficit = item["par_level"] - item["current_level"]
            lines.append(
                f"⚠️ {item['item_name'].title()}\n"
                f"   Have: {item['current_level']:g}{unit_str}  |  "
                f"Par: {item['par_level']:g}{unit_str}  |  "
                f"Need: {deficit:g}{unit_str}"
            )
        await update.message.reply_text(
            f"Low Stock — {restaurant['name']}\n"
            f"{'─' * 36}\n" +
            "\n".join(lines) +
            f"\n{'─' * 36}\n"
            f"{len(low_items)} item(s) below par level.\n"
            "Order these before next service."
        )

    # ── /stock (status — show all) ────────────────────────────────────────────
    else:
        items = get_stock_status(rid)
        if not items:
            await update.message.reply_text(
                "No stock items set up yet.\n\n"
                "Start by setting par levels:\n"
                "/stock set chicken 10 kg\n"
                "/stock set milk 12 litres\n"
                "/stock set burger buns 48\n\n"
                "Then log counts:\n"
                "/stock count chicken 3 kg"
            )
            return

        ok_lines, low_lines, uncount_lines = [], [], []
        for item in items:
            unit_str = f" {item['unit']}" if item["unit"] else ""
            par_str = f"{item['par_level']:g}{unit_str}"
            if item["current_level"] is None:
                uncount_lines.append(f"  ○ {item['item_name'].title():<25} par: {par_str}")
            elif item["current_level"] < item["par_level"]:
                deficit = item["par_level"] - item["current_level"]
                low_lines.append(
                    f"  ⚠️ {item['item_name'].title():<23} "
                    f"{item['current_level']:g}{unit_str} / {par_str}  (need {deficit:g}{unit_str})"
                )
            else:
                ok_lines.append(
                    f"  ✅ {item['item_name'].title():<23} "
                    f"{item['current_level']:g}{unit_str} / {par_str}"
                )

        sections = []
        if low_lines:
            sections.append("BELOW PAR — order now:\n" + "\n".join(low_lines))
        if ok_lines:
            sections.append("OK:\n" + "\n".join(ok_lines))
        if uncount_lines:
            sections.append("NOT YET COUNTED:\n" + "\n".join(uncount_lines))

        last_count = next(
            (i["last_count_date"] for i in items if i["last_count_date"]), None
        )
        count_note = f"Last count: {_fmt_date(last_count)}" if last_count else "No counts recorded yet"

        await update.message.reply_text(
            f"Stock Status — {restaurant['name']}\n"
            f"{'─' * 36}\n" +
            ("\n\n".join(sections)) +
            f"\n{'─' * 36}\n"
            f"{count_note}\n"
            "Use /stock count <item> <amount> to update counts."
        )


def _rota_week_bounds(ref: date, offset_weeks: int = 0):
    """Return (monday, sunday) as YYYY-MM-DD for the week containing ref + offset_weeks."""
    monday = ref - timedelta(days=ref.weekday()) + timedelta(weeks=offset_weeks)
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")


def _parse_rota_day(token: str, ref: date) -> str | None:
    """Convert a day token ('Monday', 'Mon', 'Tue', YYYY-MM-DD, DD/MM/YYYY) to YYYY-MM-DD.
    Day names resolve to the current week (Mon-Sun)."""
    token = token.strip().lower()
    monday = ref - timedelta(days=ref.weekday())
    day_map = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1, "tues": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6,
        "today": ref.weekday(),
        "tomorrow": (ref + timedelta(days=1)).weekday(),
    }
    if token == "today":
        return ref.strftime("%Y-%m-%d")
    if token == "tomorrow":
        return (ref + timedelta(days=1)).strftime("%Y-%m-%d")
    if token in day_map:
        return (monday + timedelta(days=day_map[token])).strftime("%Y-%m-%d")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(token, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _parse_shift_time(tok: str):
    """Parse a single time token like '9am', '17:00', '9', '9:30pm' → 'HH:MM' or None."""
    tok = tok.strip().lower()
    m = re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$', tok)
    if not m:
        return None
    h, mins, period = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if period == "pm" and h != 12:
        h += 12
    elif period == "am" and h == 12:
        h = 0
    elif period is None and 1 <= h <= 7:
        h += 12   # ambiguous bare numbers: treat 1-7 as pm (lunch/evening shifts)
    return f"{h:02d}:{mins:02d}"


def _parse_time_range(tok: str):
    """Parse '9am-5pm', '09:00-17:00', '9-17' → ('09:00', '17:00'). Returns (start, end) or (start, None)."""
    if "-" in tok:
        parts = tok.split("-", 1)
        return _parse_shift_time(parts[0]), _parse_shift_time(parts[1])
    return _parse_shift_time(tok), None


def _fmt_shift_time(t: str) -> str:
    """Format stored HH:MM for display. Strips leading zero from hour."""
    if not t:
        return ""
    try:
        h, m = t.split(":")
        return f"{int(h)}:{m}"
    except ValueError:
        return t


def _rota_week_label(week_start: str, week_end: str) -> str:
    """e.g. 'Mon 9 Mar – Sun 15 Mar 2026'"""
    try:
        s = datetime.strptime(week_start, "%Y-%m-%d")
        e = datetime.strptime(week_end, "%Y-%m-%d")
        return f"Mon {s.day} {s.strftime('%b')} – Sun {e.day} {e.strftime('%b %Y')}"
    except ValueError:
        return f"{week_start} to {week_end}"


def _render_rota(shifts: list, week_start: str, week_end: str, restaurant_name: str) -> str:
    """Build the rota display string for a week."""
    DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    # Index shifts by date
    by_date: dict[str, list] = {}
    for s in shifts:
        by_date.setdefault(s["shift_date"], []).append(s)

    # Walk every day of the week
    lines = [
        f"Rota — {restaurant_name}",
        f"Week: {_rota_week_label(week_start, week_end)}",
        "─" * 40,
    ]
    monday = datetime.strptime(week_start, "%Y-%m-%d")
    has_any = False
    for i in range(7):
        day_date = (monday + timedelta(days=i)).strftime("%Y-%m-%d")
        day_display = (monday + timedelta(days=i)).strftime(f"{DAY_NAMES[i]} %-d %b")
        day_shifts = by_date.get(day_date, [])
        if day_shifts:
            has_any = True
            lines.append(f"\n{day_display}")
            for s in day_shifts:
                t_start = _fmt_shift_time(s["start_time"])
                t_end = _fmt_shift_time(s["end_time"])
                time_str = f"{t_start}–{t_end}" if t_end else (t_start or "—")
                role_str = f"  ({s['role']})" if s["role"] else ""
                lines.append(f"  {s['staff_name']:<20} {time_str:<13}  [#{s['id']}]{role_str}")

    if not has_any:
        lines.append("\n(No shifts added yet)")

    lines.append("\n" + "─" * 40)
    lines.append(f"{len(shifts)} shift(s) total")
    lines.append("Add:    /rota add Monday Name 9am-5pm")
    lines.append("Remove: /rota remove <#id>")
    lines.append("Copy last week: /rota copy")
    return "\n".join(lines)


async def cmd_rota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rota                           — show this week's rota
    /rota next                      — show next week's rota
    /rota add <day> <name> <times>  — add a shift
    /rota remove <id>               — remove a shift by ID
    /rota copy                      — copy last week's rota to this week
    /rota clear                     — clear all shifts this week (asks confirmation)
    /rota clear confirm             — actually clear this week

    Examples:
      /rota add Monday John 9am-5pm
      /rota add Tuesday Sophie 12:00-20:00
      /rota add Wed Marcus 8-4
      /rota remove 42
      /rota next
      /rota copy
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    args = list(context.args) if context.args else []
    rid = restaurant["id"]
    today = date.today()
    sub = args[0].lower() if args else "show"

    # ── /rota add <day> <name> <time-range> ──────────────────────────────────
    if sub == "add":
        if len(args) < 4:
            await update.message.reply_text(
                "Usage: /rota add <day> <name> <times>\n\n"
                "Examples:\n"
                "  /rota add Monday John 9am-5pm\n"
                "  /rota add Tuesday Sophie 12:00-20:00\n"
                "  /rota add Wed Marcus 8-16\n\n"
                "Days: Monday Mon Tue Wed Thu Fri Sat Sun today tomorrow"
            )
            return

        day_token = args[1]
        shift_date = _parse_rota_day(day_token, today)
        if not shift_date:
            await update.message.reply_text(
                f"Couldn't understand day '{day_token}'.\n"
                "Use: Monday, Mon, Tue, Wed, Thu, Fri, Sat, Sun, today, tomorrow"
            )
            return

        # Last arg is time range, everything between is the name
        time_token = args[-1]
        start_time, end_time = _parse_time_range(time_token)
        if start_time is None:
            await update.message.reply_text(
                f"Couldn't understand time '{time_token}'.\n"
                "Try: 9am-5pm  or  09:00-17:00  or  9-17"
            )
            return

        staff_name = " ".join(args[2:-1]).strip()
        if not staff_name:
            await update.message.reply_text(
                "Please include a name: /rota add Monday John 9am-5pm"
            )
            return

        shift_id = add_rota_shift(rid, shift_date, staff_name, start_time, end_time or "")
        day_fmt = datetime.strptime(shift_date, "%Y-%m-%d").strftime("%-d %b (%A)")
        t_start = _fmt_shift_time(start_time)
        t_end = _fmt_shift_time(end_time) if end_time else ""
        time_display = f"{t_start}–{t_end}" if t_end else t_start
        await update.message.reply_text(
            f"Shift added ✅\n"
            f"{staff_name} — {day_fmt} — {time_display}  [#{shift_id}]\n\n"
            "View rota: /rota\n"
            "Remove: /rota remove " + str(shift_id)
        )

    # ── /rota remove <id> ────────────────────────────────────────────────────
    elif sub == "remove":
        if len(args) < 2:
            await update.message.reply_text("Usage: /rota remove <id>  (ID shown in [#..] on the rota)")
            return
        try:
            shift_id = int(args[1].lstrip("#"))
        except ValueError:
            await update.message.reply_text(f"'{args[1]}' is not a valid shift ID.")
            return
        deleted = delete_rota_shift(shift_id, rid)
        if deleted:
            await update.message.reply_text(f"Shift #{shift_id} removed.")
        else:
            await update.message.reply_text(
                f"Shift #{shift_id} not found (may already be deleted or belong to another group)."
            )

    # ── /rota copy ───────────────────────────────────────────────────────────
    elif sub == "copy":
        last_start, last_end = _rota_week_bounds(today, offset_weeks=-1)
        this_start, this_end = _rota_week_bounds(today)
        # Check destination isn't already populated
        existing = get_rota_for_week(rid, this_start, this_end)
        if existing:
            await update.message.reply_text(
                f"This week already has {len(existing)} shift(s).\n"
                "Clear this week first with /rota clear confirm, then /rota copy."
            )
            return
        copied = copy_rota_week(rid, last_start, last_end, this_start)
        if copied == 0:
            await update.message.reply_text(
                "Last week had no shifts to copy.\n"
                "Add shifts with: /rota add Monday Name 9am-5pm"
            )
            return
        await update.message.reply_text(
            f"Copied {copied} shift(s) from last week to this week. ✅\n\n"
            "View: /rota\n"
            "Remove individual shifts with /rota remove <id>"
        )

    # ── /rota clear [confirm] ─────────────────────────────────────────────────
    elif sub == "clear":
        this_start, this_end = _rota_week_bounds(today)
        confirmed = len(args) > 1 and args[1].lower() == "confirm"
        if not confirmed:
            existing = get_rota_for_week(rid, this_start, this_end)
            await update.message.reply_text(
                f"This will delete all {len(existing)} shift(s) for this week.\n\n"
                "To confirm: /rota clear confirm"
            )
            return
        deleted = clear_rota_week(rid, this_start, this_end)
        await update.message.reply_text(f"Cleared {deleted} shift(s) from this week.")

    # ── /rota next ────────────────────────────────────────────────────────────
    elif sub == "next":
        week_start, week_end = _rota_week_bounds(today, offset_weeks=1)
        shifts = get_rota_for_week(rid, week_start, week_end)
        await update.message.reply_text(_render_rota(shifts, week_start, week_end, restaurant["name"]))

    # ── /rota (show this week) ────────────────────────────────────────────────
    else:
        week_start, week_end = _rota_week_bounds(today)
        shifts = get_rota_for_week(rid, week_start, week_end)
        await update.message.reply_text(_render_rota(shifts, week_start, week_end, restaurant["name"]))


async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /dashboard — get a private link to your restaurant's live web dashboard.
    The link shows rota, stock, invoices, financials and recent activity.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    token = get_or_create_dashboard_token(restaurant["id"])

    # Build the base URL from RAILWAY_PUBLIC_DOMAIN env var if set, else generic instructions
    base_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    if base_url:
        url = f"https://{base_url}/dashboard/{token}"
        await update.message.reply_text(
            f"Your live dashboard:\n{url}\n\n"
            "Bookmark it — it shows:\n"
            "  • This week's rota\n"
            "  • Stock levels (red = low)\n"
            "  • Outstanding invoices\n"
            "  • Month-to-date P&L\n"
            "  • Recent activity & 86 list\n\n"
            "The page auto-refreshes every 60 seconds.\n"
            "Keep this link private — anyone with it can view your data."
        )
    else:
        await update.message.reply_text(
            f"Dashboard token: {token}\n\n"
            "Your dashboard is available at:\n"
            "  http://<your-server>/dashboard/" + token + "\n\n"
            "On Railway: set RAILWAY_PUBLIC_DOMAIN in Variables for a clean URL.\n\n"
            "The dashboard shows rota, stock, invoices, P&L and recent activity.\n"
            "Keep this link private — anyone with it can view your data."
        )


async def cmd_groupreport(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /groupreport [period]

    Consolidated P&L across ALL restaurants registered to this bot instance.
    Useful for franchise/multi-site owners running their own bot.

    Examples:
      /groupreport              — this month
      /groupreport last month   — previous calendar month
      /groupreport March 2026   — specific month
    """
    # Must be in a registered group or the support chat — give a helpful message otherwise
    chat_id = str(update.effective_chat.id)
    calling_restaurant = get_restaurant_by_group(chat_id)

    query = " ".join(context.args).strip() if context.args else "this month"
    date_range = _parse_date_range(query)

    if not date_range:
        await update.message.reply_text(
            f"Couldn't understand period \"{query}\".\n"
            "Try: this month, last month, March 2026"
        )
        return

    start_date, end_date = date_range
    period_label = (
        _fmt_date(start_date) if start_date == end_date
        else f"{_fmt_date(start_date)} to {_fmt_date(end_date)}"
    )

    all_restaurants = get_all_restaurants()
    if not all_restaurants:
        await update.message.reply_text("No restaurants registered yet.")
        return

    # Gather financials for every site
    sites = []
    for r in all_restaurants:
        fin = get_financial_summary(r["id"], start_date, end_date)
        sites.append({
            "name": r["name"],
            "revenue": fin["revenue_total"],
            "costs": fin["cost_total"],
            "labour": fin["labour_total"],
            "profit": fin["gross_profit"],
            "food_margin": fin["food_margin_pct"],
            "net_margin": fin["net_margin_pct"],
        })

    # Filter to sites that have any data
    active_sites = [s for s in sites if s["revenue"] > 0 or s["costs"] > 0 or s["labour"] > 0]

    if not active_sites:
        await update.message.reply_text(
            f"No financial data found for {period_label} across any of the "
            f"{len(all_restaurants)} registered restaurant(s).\n\n"
            "Revenue is captured from voice/text updates mentioning takings.\n"
            "Costs are captured when invoice photos are sent.\n"
            "Labour is recorded via /labour."
        )
        return

    # Group totals
    total_revenue = sum(s["revenue"] for s in active_sites)
    total_costs = sum(s["costs"] for s in active_sites)
    total_labour = sum(s["labour"] for s in active_sites)
    total_profit = sum(s["profit"] for s in active_sites)
    group_net_margin = round(total_profit / total_revenue * 100, 1) if total_revenue else 0.0
    group_food_margin = (
        round((total_revenue - total_costs) / total_revenue * 100, 1) if total_revenue else 0.0
    )

    # Per-site breakdown lines
    divider = "─" * 44
    site_lines = []
    for s in active_sites:
        margin_flag = ""
        if s["net_margin"] < 5:
            margin_flag = " ⚠️"
        elif s["net_margin"] >= 15:
            margin_flag = " ✅"
        sym = _cs(restaurant)
        site_lines.append(
            f"\n{s['name']}\n"
            f"  Revenue:  {sym}{s['revenue']:>9,.2f}  |  Costs: {sym}{s['costs']:>8,.2f}\n"
            f"  Labour:   {sym}{s['labour']:>9,.2f}  |  Profit: {sym}{s['profit']:>7,.2f}\n"
            f"  Food GP: {s['food_margin']:>5.1f}%   |  Net: {s['net_margin']:>5.1f}%{margin_flag}"
        )

    sym = _cs(restaurant)
    context_note = (
        f"\n\n(Showing {len(active_sites)} of {len(all_restaurants)} site(s) — "
        f"{len(all_restaurants) - len(active_sites)} have no data this period)"
        if len(active_sites) < len(all_restaurants) else ""
    )

    await update.message.reply_text(
        f"Group Report — All Sites\n"
        f"Period: {period_label}\n"
        f"{divider}\n"
        f"GROUP TOTALS\n"
        f"  Revenue:         {sym}{total_revenue:>10,.2f}\n"
        f"  Invoiced costs:  {sym}{total_costs:>10,.2f}\n"
        f"  Labour:          {sym}{total_labour:>10,.2f}\n"
        f"  {divider[:30]}\n"
        f"  Net profit:      {sym}{total_profit:>10,.2f}\n"
        f"  Food GP margin:  {group_food_margin:>9.1f}%\n"
        f"  Net margin:      {group_net_margin:>9.1f}%\n"
        f"{divider}\n"
        f"PER SITE BREAKDOWN"
        + "".join(site_lines)
        + f"\n{divider}"
        + context_note
        + "\n\nUse /export xero or /export sage per site for accounting imports."
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

        sym = _cs(restaurant)
        lines.append(f"#{inv['id']}  {(inv['supplier_name'] or 'Unknown'):.<25} {sym}{amount:>8,.2f}  {flag}")

    invoices_text = "\n".join(lines)
    sym = _cs(restaurant)
    await update.message.reply_text(
        f"Outstanding Invoices — {restaurant['name']}\n"
        f"{'─' * 40}\n"
        f"{invoices_text}\n"
        f"{'─' * 40}\n"
        f"Total outstanding: {sym}{total:,.2f}\n\n"
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

    sym = _cs(restaurant)
    if inv["paid"]:
        await update.message.reply_text(
            f"Invoice #{invoice_id} ({inv['supplier_name']}, {sym}{inv['total_amount']:.2f}) "
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
        f"Your registration is intact — TradeFlow will continue capturing new messages.\n"
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
            "Ask anything about TradeFlow.\n\n"
            "Examples:\n"
            "  /ask how do I fix a wrong entry?\n"
            "  /ask how do I record tips from last week?\n"
            "  /ask what is the best way to get the weekly report?\n"
            "  /ask how do I import data from before I started using TradeFlow?\n"
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
    Send a message to the TradeFlow support team.
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
                f"Response from the TradeFlow team:\n{reply_text}\n\n"
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

    sym = _cs(restaurant)
    lines = []
    for t in events:
        amount = t["gross_amount"] or 0
        tip_type = (t["tip_type"] or "unknown").upper()
        shift = t["shift"] or "unspecified shift"
        lines.append(f"  {_fmt_date(t['event_date'])}  {tip_type}  {sym}{amount:.2f}  ({shift})")

    events_text = "\n".join(lines)

    await update.message.reply_text(
        f"Tips Log — {restaurant['name']}\n"
        f"Period: {period_label}\n"
        f"{'─' * 40}\n\n"
        f"Card tips:    {sym}{summary['card']:>8,.2f}\n"
        f"Cash tips:    {sym}{summary['cash']:>8,.2f}\n"
        f"Unknown type: {sym}{summary['unknown']:>8,.2f}\n"
        f"{'─' * 40}\n"
        f"Total:        {sym}{summary['total']:>8,.2f}\n\n"
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

    sym = _cs(restaurant)
    await update.message.reply_text(
        f"Generating Tips Act compliance record for {period_label}...\n"
        f"({len(events)} events, {sym}{summary['total']:.2f} total)"
    )

    events_as_dicts = [dict(e) for e in events]
    report = generate_tips_report(events_as_dicts, summary, restaurant["name"], period_label, sym)

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
        "RESTAURANT IQ — HOW IT WORKS\n"
        "════════════════════════════════════\n\n"
        "Your team sends messages to this group as normal.\n"
        "TradeFlow reads every message, extracts the useful data,\n"
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
        "Type anything — TradeFlow captures and categorises it.\n\n"
        "Examples:\n"
        "  \"Butcher raised beef prices by 9% this week\"\n"
        "  \"Ahmed was 40 mins late — third time this month\"\n"
        "  \"Truffle arancini selling really well, customers loving it\"\n"
        "  \"Saturday: 96 covers, £3,250 takings\""
    )

    # Message 2: What gets extracted + limitations
    await update.message.reply_text(
        "WHAT RESTAURANT IQ EXTRACTS AUTOMATICALLY\n"
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
        "  ✗ Revenue you don't report — TradeFlow only knows what your team tells it\n"
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
        "  Ask what happened on any day or week.\n"
        "  The AI summarises all entries for that period.\n"
        "  Try: /recall yesterday   /recall 5 May   /recall last week   /recall March\n\n"
        "/outstanding\n"
        "  All unpaid invoices sorted by due date.\n"
        "  Shows supplier, amount, and days until due (or days overdue).\n"
        "  An automatic 9am reminder is also sent to this group\n"
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
        "These features are unique to TradeFlow and built specifically\n"
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
        "TradeFlow tracks due dates from the invoice date, so late uploads\n"
        "mean you miss payment warnings.\n\n"
        "YOUR TEAM:\n"
        "Add all staff to this Telegram group.\n"
        "TradeFlow records who sent each update, so the weekly report\n"
        "can link issues and wins to the right shifts and people.\n\n"
        "WHAT GOOD ENTRIES LOOK LIKE:\n"
        "  ✅ \"Friday lunch: 44 covers, £1,180. Veg soup sold out at 1pm.\n"
        "       Two tables complimented the new sea bass.\"\n\n"
        "  ✅ [Photo of invoice — flat on desk, clear light, full page visible]\n\n"
        "  ✅ \"Walk-in fridge alarm at 6am — engineer confirmed false alarm.\"\n\n"
        "WHAT GETS IGNORED:\n"
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

def _fmt_date_uk(iso_date: str) -> str:
    """Convert YYYY-MM-DD to DD/MM/YYYY for UK accounting software."""
    if not iso_date:
        return ""
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return iso_date


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /export [format] [period]

    Formats:
      (none)    — general entries log (Excel/accountant review)
      xero      — Xero Bills import CSV (purchase invoices)
      sage      — Sage 50 purchase journal CSV
      payroll   — Labour cost entries CSV (wages/agency/contractor)

    Examples:
      /export                    — this week's entries
      /export last month         — last month's entries
      /export xero               — Xero bills for this month
      /export xero last month    — Xero bills for last month
      /export sage this month    — Sage purchase journal for this month
      /export payroll last month — Labour costs for last month
    """
    import csv
    import io

    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    # Detect optional format keyword as first argument
    args = list(context.args) if context.args else []
    fmt = "general"
    FORMATS = {"xero", "sage", "payroll"}
    if args and args[0].lower() in FORMATS:
        fmt = args[0].lower()
        args = args[1:]

    period_query = " ".join(args).strip() if args else "this month"
    date_range = _parse_date_range(period_query)

    if not date_range:
        await update.message.reply_text(
            f"Couldn't understand period \"{period_query}\".\n"
            "Try: this week, this month, last month, March 2026"
        )
        return

    start_date, end_date = date_range
    safe_name = restaurant["name"].replace(" ", "_").replace("/", "-")
    period_label = f"{start_date}_to_{end_date}"
    output = io.StringIO()

    # ── XERO BILLS IMPORT ──────────────────────────────────────────────────────
    if fmt == "xero":
        invoices = get_invoices_for_period(restaurant["id"], start_date, end_date)
        if not invoices:
            await update.message.reply_text(
                f"No invoices found for {_fmt_date(start_date)} to {_fmt_date(end_date)}.\n"
                "Invoices are captured when you send a photo of a supplier invoice."
            )
            return

        writer = csv.writer(output)
        # Xero UK Bills import format (required columns marked *)
        writer.writerow([
            "*ContactName", "*InvoiceNumber", "*InvoiceDate", "*DueDate",
            "Description", "Quantity", "*UnitAmount", "Discount",
            "*AccountCode", "*TaxType", "TaxAmount", "Currency", "BrandingTheme",
        ])
        for idx, inv in enumerate(invoices, start=1):
            net = round((inv["total_amount"] or 0) - (inv["vat"] or 0), 2)
            vat = round(inv["vat"] or 0, 2)
            tax_type = "20% (VAT on Expenses)" if vat > 0 else "No VAT"
            inv_number = f"INV-{inv['id']:04d}"
            inv_date = _fmt_date_uk(inv["invoice_date"] or start_date)
            due_date = _fmt_date_uk(inv["due_date"] or end_date)
            writer.writerow([
                inv["supplier_name"] or "Unknown Supplier",
                inv_number,
                inv_date,
                due_date,
                inv["description"] or f"Purchase from {inv['supplier_name'] or 'supplier'}",
                1,                  # Quantity
                net,                # UnitAmount (net of VAT)
                "",                 # Discount
                "429",              # AccountCode — Xero default "General Expenses" (change to 300 for food purchases)
                tax_type,
                vat if vat > 0 else "",
                "GBP",
                "",
            ])

        csv_bytes = output.getvalue().encode("utf-8-sig")
        filename = f"{safe_name}_XERO_bills_{period_label}.csv"
        caption = (
            f"Xero Bills Import — {restaurant['name']}\n"
            f"{_fmt_date(start_date)} to {_fmt_date(end_date)}\n"
            f"{len(invoices)} invoice(s)\n\n"
            "How to import: Xero > Accounts Payable > Import\n"
            "Tip: Change AccountCode 429 to 300 for food/drink purchases."
        )

    # ── SAGE 50 PURCHASE JOURNAL ───────────────────────────────────────────────
    elif fmt == "sage":
        invoices = get_invoices_for_period(restaurant["id"], start_date, end_date)
        if not invoices:
            await update.message.reply_text(
                f"No invoices found for {_fmt_date(start_date)} to {_fmt_date(end_date)}.\n"
                "Invoices are captured when you send a photo of a supplier invoice."
            )
            return

        writer = csv.writer(output)
        # Sage 50 Accounts purchase transaction import format
        writer.writerow([
            "Type", "Account", "N/C", "Dept", "Date", "Ref",
            "Details", "Net Amount", "T/C", "VAT Amount",
        ])
        for inv in invoices:
            net = round((inv["total_amount"] or 0) - (inv["vat"] or 0), 2)
            vat = round(inv["vat"] or 0, 2)
            tax_code = "T1" if vat > 0 else "T0"   # T1 = 20% standard, T0 = zero rated
            # Sage supplier account code: first 8 chars of supplier name, uppercase
            supplier_code = (inv["supplier_name"] or "UNKNOWN").upper().replace(" ", "")[:8]
            inv_date = _fmt_date_uk(inv["invoice_date"] or start_date)
            ref = f"RIQ{inv['id']:04d}"
            writer.writerow([
                "PI",               # Purchase Invoice
                supplier_code,
                "5000",             # Nominal Code — Purchases (change to 5001 for food, 5002 for drinks, etc.)
                "0",                # Department
                inv_date,
                ref,
                inv["description"] or f"Purchase from {inv['supplier_name'] or 'supplier'}",
                f"{net:.2f}",
                tax_code,
                f"{vat:.2f}",
            ])

        csv_bytes = output.getvalue().encode("utf-8-sig")
        filename = f"{safe_name}_SAGE_purchases_{period_label}.csv"
        caption = (
            f"Sage 50 Purchase Journal — {restaurant['name']}\n"
            f"{_fmt_date(start_date)} to {_fmt_date(end_date)}\n"
            f"{len(invoices)} invoice(s)\n\n"
            "How to import: Sage 50 > File > Import > Audit Trail Transactions\n"
            "Tip: Nominal Code 5000 = Purchases. Split into 5001 (food) / 5002 (drinks) if needed."
        )

    # ── PAYROLL / LABOUR CSV ───────────────────────────────────────────────────
    elif fmt == "payroll":
        labour = get_labour_for_period(restaurant["id"], start_date, end_date)
        if not labour:
            await update.message.reply_text(
                f"No labour entries found for {_fmt_date(start_date)} to {_fmt_date(end_date)}.\n"
                "Log labour costs with: /labour £450 wages Monday"
            )
            return

        writer = csv.writer(output)
        writer.writerow([
            "Date", "Reference", "Description", "Shift", "Hours", "Amount (£)",
            "Weekly Total", "Notes",
        ])
        # Group by week for running totals
        weekly = {}
        for l in labour:
            wk = l["labour_date"][:7]  # YYYY-MM key
            weekly[wk] = weekly.get(wk, 0) + (l["amount"] or 0)

        week_seen = {}
        for l in labour:
            wk = l["labour_date"][:7]
            if wk not in week_seen:
                week_seen[wk] = 0
            week_seen[wk] += l["amount"] or 0
            ref = f"LAB{l['id']:04d}"
            writer.writerow([
                _fmt_date_uk(l["labour_date"]),
                ref,
                l["description"] or "Labour cost",
                l["shift"] or "",
                f"{l['hours']:.1f}" if l["hours"] else "",
                f"{l['amount']:.2f}",
                f"{week_seen[wk]:.2f}",
                "",
            ])

        # Summary row
        total = sum(l["amount"] or 0 for l in labour)
        writer.writerow([])
        writer.writerow(["TOTAL", "", "", "", "", f"{total:.2f}", "", ""])

        csv_bytes = output.getvalue().encode("utf-8-sig")
        filename = f"{safe_name}_PAYROLL_{period_label}.csv"
        caption = (
            f"Labour Cost Export — {restaurant['name']}\n"
            f"{_fmt_date(start_date)} to {_fmt_date(end_date)}\n"
            f"{len(labour)} entries | Total: £{total:.2f}\n\n"
            "Compatible with BrightPay, Sage Payroll, and Excel payroll templates."
        )

    # ── GENERAL ENTRIES (default) ──────────────────────────────────────────────
    else:
        entries = get_entries_with_staff(restaurant["id"], start_date, end_date)
        if not entries:
            await update.message.reply_text(
                f"No entries found for {_fmt_date(start_date)} to {_fmt_date(end_date)}."
            )
            return

        writer = csv.writer(output)
        writer.writerow(["Date", "Time", "Type", "Staff", "Category", "Summary", "Raw Text", "Urgency", "Revenue (£)", "Covers"])

        for e in entries:
            summary = urgency = revenue = covers = ""
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
                e["entry_date"], e["entry_time"], e["entry_type"],
                e["staff_name"] or "", e["category"] or "",
                summary, (e["raw_text"] or "")[:300],
                urgency, revenue, covers,
            ])

        csv_bytes = output.getvalue().encode("utf-8-sig")
        filename = f"{safe_name}_{period_label}.csv"
        caption = (
            f"Data export: {restaurant['name']}\n"
            f"{_fmt_date(start_date)} to {_fmt_date(end_date)}\n"
            f"{len(entries)} entries\n\n"
            "Also try:\n"
            "/export xero — Xero Bills import\n"
            "/export sage — Sage 50 purchase journal\n"
            "/export payroll — Labour cost sheet"
        )

    await update.message.reply_document(
        document=csv_bytes,
        filename=filename,
        caption=caption,
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

            report_text = generate_weekly_report(entries_data, restaurant["name"], financials, _cs(restaurant))
            save_weekly_report(restaurant["id"], week_start, week_end, report_text)

            safe_name = restaurant["name"].replace(" ", "_").replace("/", "-")
            pdf_path = os.path.join(REPORTS_DIR, f"{safe_name}_{week_start}.pdf")
            generate_pdf_report(report_text, restaurant["name"], week_start, week_end, pdf_path)

            header = f"TRADEFLOW WEEKLY BRIEFING\n{'=' * 34}\n\n"
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


# ── Version / deployment info ─────────────────────────────────────────────────

_VERSION_CACHE: dict = {}   # cached on first call so GitHub API is only hit once

_GITHUB_REPO = "kfrem/restaurant-iq-bot"   # update if repo is ever renamed


def _get_version_info() -> dict:
    """
    On Railway: reads RAILWAY_GIT_COMMIT_SHA + calls GitHub API for the
    real commit message and timestamp.  Results are cached for the lifetime
    of the process so the API is called at most once per deploy.
    Local fallback: uses git subprocess.
    """
    global _VERSION_CACHE
    if _VERSION_CACHE:
        return _VERSION_CACHE

    full_sha  = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")
    branch    = os.environ.get("RAILWAY_GIT_BRANCH", "")
    deploy_id = os.environ.get("RAILWAY_DEPLOYMENT_ID", "—")

    if full_sha:
        short_sha = full_sha[:7]
        msg = commit_date = None
        try:
            url = f"https://api.github.com/repos/{_GITHUB_REPO}/commits/{full_sha}"
            req = _urllib_req.Request(url, headers={"User-Agent": "restaurant-iq-bot/1.0"})
            with _urllib_req.urlopen(req, timeout=8) as resp:
                data = _json_mod.loads(resp.read())
            msg = data["commit"]["message"].split("\n")[0]   # first line only
            raw_date = data["commit"]["author"]["date"]      # e.g. "2026-03-07T12:00:00Z"
            dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            commit_date = dt.strftime("%d %b %Y at %H:%M UTC")
        except Exception:
            pass   # network or rate-limit — leave as None

        _VERSION_CACHE = {
            "source":    "railway",
            "hash":      short_sha,
            "branch":    branch or "main",
            "date":      commit_date or "see Railway dashboard",
            "msg":       msg or "see GitHub",
            "deploy_id": deploy_id,
        }
        return _VERSION_CACHE

    # ── Local / non-Railway fallback — use git directly ──────────────────────
    def _run(args):
        return subprocess.check_output(args, stderr=subprocess.DEVNULL).decode().strip()
    try:
        short_sha   = _run(["git", "rev-parse", "--short", "HEAD"])
        raw_date    = _run(["git", "log", "-1", "--format=%ci"])
        dt          = datetime.fromisoformat(raw_date)
        commit_date = dt.strftime("%d %b %Y at %H:%M UTC")
        msg         = _run(["git", "log", "-1", "--format=%s"])
        branch      = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        _VERSION_CACHE = {"source": "local", "hash": short_sha, "branch": branch,
                          "date": commit_date, "msg": msg, "deploy_id": "—"}
    except Exception:
        _VERSION_CACHE = {"source": "unknown", "hash": "?", "branch": "?",
                          "date": "?", "msg": "?", "deploy_id": "—"}
    return _VERSION_CACHE


async def cmd_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/currency [CODE] — view or set the currency for this business.

    Supported codes: GBP, USD, EUR, NGN, KES, ZAR, GHS, UGX, TZS, XOF

    Examples:
      /currency          — show current currency
      /currency USD      — switch to US Dollar ($)
      /currency NGN      — switch to Nigerian Naira (₦)
      /currency KES      — switch to Kenyan Shilling (KSh)
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    chat_id = str(update.effective_chat.id)

    if not context.args:
        code, sym = get_restaurant_currency(chat_id)
        display_name = SUPPORTED_CURRENCIES.get(code, (sym, code))[1]
        supported = "\n".join(
            f"  {c} — {sym_} ({name})"
            for c, (sym_, name) in SUPPORTED_CURRENCIES.items()
        )
        await update.message.reply_text(
            f"Currency — {restaurant['name']}\n"
            f"{'─' * 36}\n"
            f"Current: {code} ({sym}) — {display_name}\n\n"
            f"To change: /currency CODE\n\n"
            f"Supported currencies:\n{supported}"
        )
        return

    requested = context.args[0].upper()
    try:
        code, sym = set_restaurant_currency(chat_id, requested)
        display_name = SUPPORTED_CURRENCIES[code][1]
        await update.message.reply_text(
            f"Currency updated to *{code}* ({sym}) — {display_name}\n\n"
            f"All financial displays in {restaurant['name']} will now use {sym}.",
            parse_mode="Markdown",
        )
    except ValueError:
        supported_codes = ", ".join(SUPPORTED_CURRENCIES.keys())
        await update.message.reply_text(
            f"Unsupported currency code: {requested}\n\n"
            f"Supported codes: {supported_codes}\n"
            f"Example: /currency USD"
        )


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/version — show when this bot was last deployed and what changed."""
    info = _get_version_info()

    text = (
        f"*TradeFlow* — v2.0 (Multi-currency & International)\n"
        f"Commit: `{info['hash']}`\n"
        f"Deployed: {info['date']}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


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
            f"  2. Add TradeFlow to that group\n"
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

    # Registration wizard — must be added before generic message handlers
    _text_filter = filters.TEXT & ~filters.COMMAND
    reg_conv = ConversationHandler(
        entry_points=[
            CommandHandler("register", cmd_register),
            CommandHandler("profile", cmd_profile),
        ],
        states={
            REG_NAME:     [MessageHandler(_text_filter, _reg_got_name)],
            REG_LOCATION: [MessageHandler(_text_filter, _reg_got_location)],
            REG_CONTACT:  [MessageHandler(_text_filter, _reg_got_contact)],
            REG_LEGAL:    [MessageHandler(_text_filter, _reg_got_legal)],
            REG_BUSINESS: [MessageHandler(_text_filter, _reg_got_business)],
        },
        fallbacks=[CommandHandler("cancel", _reg_cancel)],
        per_chat=True,
        per_user=True,
        allow_reentry=True,
    )
    app.add_handler(reg_conv)

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("correct", cmd_correct))
    app.add_handler(CommandHandler("deletelast", cmd_deletelast))
    app.add_handler(CommandHandler("weeklyreport", cmd_weekly_report))
    app.add_handler(CommandHandler("recall", cmd_recall))
    app.add_handler(CommandHandler("financials", cmd_financials))
    app.add_handler(CommandHandler("groupreport", cmd_groupreport))
    app.add_handler(CommandHandler("outstanding", cmd_outstanding))
    app.add_handler(CommandHandler("markpaid", cmd_markpaid))
    app.add_handler(CommandHandler("currency", cmd_currency))
    app.add_handler(CommandHandler("version", cmd_version))
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
    app.add_handler(CommandHandler("stock", cmd_stock))
    app.add_handler(CommandHandler("rota", cmd_rota))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
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

    # Start web dashboard server on $PORT (Railway) or 8080 (local)
    _port = int(os.environ.get("PORT", 8080))
    start_dashboard_server(_port)

    logger.info("TradeFlow Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
