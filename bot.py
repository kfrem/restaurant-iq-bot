"""
Restaurant-IQ — Telegram Bot
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The AI chief of staff for independent restaurant owners.
Staff send voice notes, photos and texts. Owners receive weekly financial intelligence.

Run:  python bot.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMMANDS
  /start          Welcome + usage guide
  /register       Register this Telegram group as a restaurant (owner)
  /status         Weekly entry count + subscription status
  /today          Quick end-of-day text summary (no PDF)
  /weeklyreport   Full AI briefing + PDF (also auto-sent weekly)
  /history        List past reports; /history YYYY-MM-DD to retrieve one
  /metrics        KPI dashboard: food cost %, GP margin, covers vs targets
  /compare        This week vs last week analysis
  /suppliers      Supplier price changes detected from invoices
  /targets        Set KPI targets and restaurant type
  /benchmark      Compare KPIs to UK industry benchmarks (Enterprise)
  /export         Download this week's entries as CSV
  /deletedata     Delete entries >90 days (GDPR, owner only)
  /upgrade        View plans and subscription status
  /myanalyst      Your assigned advisor details (Managed/Enterprise)
  /findsupplier   Search UK supplier directory (Enterprise full list)
  /flivio         Open your Flivio analytics dashboard (Managed/Enterprise)
  /analyst        Internal analyst commands (team use only)

MESSAGES (all auto-analysed)
  Voice note → Whisper transcription → AI extraction → stored
  Photo      → Vision model reads invoice/receipt → stored
  Text       → Fast AI categorisation → stored
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import csv
import io
import json
import logging
import os
from datetime import datetime, time as dtime, timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ai_client import (
    analyze_text_entry,
    analyze_invoice_photo,
    generate_today_summary,
    generate_weekly_report,
    generate_comparison_report,
    generate_supplier_intelligence,
    is_healthy,
    backend_name,
)
from config import (
    ADMIN_TELEGRAM_ID,
    ANALYST_REVIEW_WINDOW_HOURS,
    ANALYST_TELEGRAM_IDS,
    FLIVIO_DASHBOARD_URL,
    FLASH_REPORT_TIME,
    REPORT_DAY,
    REPORT_TIME,
    TELEGRAM_BOT_TOKEN,
)
from crm import (
    add_analyst_note,
    approve_report,
    assign_analyst,
    client_health_score,
    create_analyst,
    create_pending_report,
    format_analyst_digest,
    format_analyst_note_for_report,
    get_all_analysts,
    get_analyst_by_telegram_id,
    get_analyst_for_restaurant,
    get_clients_for_analyst,
    get_hours_summary_for_analyst,
    get_hours_this_week,
    get_pending_report,
    get_pending_report_by_restaurant,
    get_pending_reports_for_analyst,
    log_analyst_hours,
    set_pending_report_note,
)
from supplier_db import format_supplier_results, search_suppliers
from flivio_bridge import (
    export_entries_to_flivio_csv,
    get_flivio_dashboard_url,
    get_integration_status,
)
from database import (
    add_compliance_item,
    complete_compliance_item,
    delete_all_entries,
    delete_compliance_item,
    delete_menu_item,
    delete_old_entries,
    get_all_restaurants,
    get_compliance_items,
    get_compliance_items_due_soon,
    get_entries_for_period,
    get_energy_logs,
    get_historic_supplier_prices,
    get_menu_items,
    get_noshow_logs,
    get_noshow_summary,
    get_or_register_staff,
    get_overhead_summary,
    get_prev_week_entries,
    get_report_by_week,
    get_restaurant_by_group,
    get_restaurant_by_id,
    get_supplier_prices,
    get_week_entries,
    get_weekly_overhead_estimate,
    get_weekly_reports,
    init_db,
    log_noshow,
    log_overhead,
    OVERHEAD_KEYWORD_MAP,
    register_restaurant,
    register_staff,
    save_entry,
    save_supplier_prices,
    save_weekly_report,
    set_google_place_id,
    update_known_balance,
    update_last_review_time,
    update_restaurant_targets,
    upsert_menu_item,
)
from intelligence import (
    build_kpis,
    detect_price_changes,
    ENERGY_SAVING_TIPS,
    extract_supplier_prices,
    format_allergen_log,
    format_benchmark_comparison,
    format_cash_reconciliation,
    format_cashflow_forecast,
    format_energy_dashboard,
    format_kpi_dashboard,
    format_labour_dashboard,
    format_menu_profitability,
    format_noshow_analysis,
    format_overhead_dashboard,
    format_price_changes,
    format_revenue_growth_advisor,
    format_supplier_reliability,
    format_vat_summary,
    format_waste_report,
)
from report_generator import generate_pdf_report
from subscription import (
    get_tier,
    has_feature,
    has_human_advisor,
    is_active,
    status_summary,
    trial_banner,
    trial_days_remaining,
    upgrade_prompt,
)
from transcriber import transcribe_audio

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

REPORTS_DIR = "reports"
VOICE_DIR   = "voice_files"
PHOTO_DIR   = "photo_files"

URGENCY_ICONS = {"high": "🔴", "medium": "🟡", "low": "🟢"}

# Scheduled report day-name → PTB JobQueue int (0=Monday … 6=Sunday)
_DAYS_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

for _d in [REPORTS_DIR, VOICE_DIR, PHOTO_DIR]:
    os.makedirs(_d, exist_ok=True)


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _ensure_staff(restaurant_id: int, user):
    name = (user.first_name or "") + (" " + user.last_name if user.last_name else "")
    return get_or_register_staff(restaurant_id, str(user.id), name.strip() or str(user.id))


async def _require_restaurant(update: Update):
    r = get_restaurant_by_group(str(update.effective_chat.id))
    if not r:
        await update.message.reply_text(
            "This group isn't registered yet.\n"
            "Owner: use /register YourRestaurantName to get started."
        )
        return None
    return r


async def _require_active(update: Update, restaurant) -> bool:
    """Return True if subscription is active; otherwise reply with upgrade message."""
    if is_active(restaurant):
        return True
    await update.message.reply_text(upgrade_prompt(restaurant))
    return False


async def _require_feature(update: Update, restaurant, feature: str) -> bool:
    """Return True if this tier includes the feature; otherwise reply with upgrade nudge."""
    if has_feature(restaurant, feature):
        return True
    await update.message.reply_text(
        f"This feature is available on the Growth plan and above.\n\n"
        + upgrade_prompt(restaurant)
    )
    return False


def _is_owner(update: Update, restaurant) -> bool:
    return str(update.effective_user.id) == str(restaurant["owner_telegram_id"])


def _build_entries_data(entries) -> list:
    """Convert DB rows into the dict format used by ai_client and intelligence modules."""
    result = []
    for e in entries:
        entry = {
            "date":     e["entry_date"],
            "time":     e["entry_time"],
            "type":     e["entry_type"],
            "raw_text": e["raw_text"] or "",
        }
        if e["structured_data"]:
            try:
                entry["analysis"] = json.loads(e["structured_data"])
            except json.JSONDecodeError:
                pass
        result.append(entry)
    return result


def _split_report_for_telegram(report_text: str) -> list[str]:
    """
    Split a report into ≤3900-char chunks at ## section boundaries.
    Telegram's hard limit is 4096 chars; we leave headroom for the header.
    """
    header  = "RESTAURANT-IQ WEEKLY BRIEFING\n" + "═" * 34 + "\n\n"
    max_len = 3900

    if len(header) + len(report_text) <= max_len:
        return [header + report_text]

    chunks  = []
    current = header
    for line in report_text.split("\n"):
        if line.startswith("## ") and len(current) > len(header) and len(current) + len(line) > max_len:
            chunks.append(current.rstrip())
            current = line + "\n"
        elif len(current) + len(line) + 1 > max_len:
            chunks.append(current.rstrip())
            current = line + "\n"
        else:
            current += line + "\n"
    if current.strip():
        chunks.append(current.rstrip())

    return chunks or [header + report_text[:max_len]]


def _week_bounds(offset_weeks: int = 0):
    """Return (week_start_str, week_end_str) for current or past weeks."""
    now   = datetime.now()
    start = now - timedelta(days=now.weekday()) - timedelta(weeks=offset_weeks)
    end   = start + timedelta(days=6)
    return start.strftime("%Y-%m-%d"), min(end, now).strftime("%Y-%m-%d")


async def _deliver_weekly_report(send_text, send_doc, restaurant, entries,
                                  prev_entries=None, triggered_by_schedule=False,
                                  bot=None):
    """
    Core weekly report logic — shared between /weeklyreport and the scheduled job.
    `send_text` and `send_doc` are async callables so this works for both contexts.
    For Managed/Enterprise tiers the AI draft is routed to the assigned analyst
    for review before delivery (human-in-the-loop). `bot` is required for that path.
    """
    if not entries:
        if not triggered_by_schedule:
            await send_text(
                "No data captured this week yet.\n"
                "Send voice notes, photos or texts first, then run /weeklyreport again."
            )
        return

    n = len(entries)
    await send_text(
        f"{'Good morning! Generating' if triggered_by_schedule else 'Generating'} your weekly "
        f"briefing from {n} entr{'y' if n == 1 else 'ies'}…\n"
        "This may take 1–2 minutes."
    )

    entries_data = _build_entries_data(entries)
    prev_data    = _build_entries_data(prev_entries) if prev_entries else []

    # Build KPIs for context
    current_kpis = build_kpis(entries_data)
    prev_kpis    = build_kpis(prev_data) if prev_data else {}

    # Supplier intelligence
    current_prices  = extract_supplier_prices(entries_data)
    historic_prices = get_historic_supplier_prices(restaurant["id"])
    price_changes   = detect_price_changes(current_prices, historic_prices)

    kpi_context      = format_kpi_dashboard(current_kpis, prev_kpis or None,
                                             restaurant["name"],
                                             float(restaurant["target_food_cost_pct"] or 30),
                                             restaurant["restaurant_type"] or "casual")
    supplier_context = format_price_changes(price_changes)

    report_text = generate_weekly_report(
        entries_data, restaurant["name"],
        kpi_context=kpi_context,
        supplier_alert_context=supplier_context if price_changes else "",
        tier=get_tier(restaurant),
    )

    week_start, week_end = _week_bounds()
    save_weekly_report(restaurant["id"], week_start, week_end, report_text)

    # Save current supplier prices for next week's comparison
    if current_prices:
        save_supplier_prices(restaurant["id"], current_prices, week_end)

    # Generate PDF
    safe_name = restaurant["name"].replace(" ", "_").replace("/", "-")
    pdf_path  = os.path.join(REPORTS_DIR, f"{safe_name}_{week_start}.pdf")
    generate_pdf_report(
        report_text, restaurant["name"], week_start, week_end, pdf_path,
        kpi_summary=kpi_context,
    )

    # ── Human-in-the-loop for Managed / Enterprise ──────────────────────────
    if has_human_advisor(restaurant) and bot:
        analyst = get_analyst_for_restaurant(restaurant["id"])
        if analyst and analyst.get("telegram_id"):
            pending_id = create_pending_report(
                restaurant["id"], report_text, pdf_path, week_start
            )
            analyst_tid = analyst["telegram_id"]
            try:
                await bot.send_message(
                    chat_id=analyst_tid,
                    text=(
                        f"📋 NEW REPORT TO REVIEW\n"
                        f"{'─' * 30}\n"
                        f"Client: {restaurant['name']}\n"
                        f"Week:   {week_start}\n"
                        f"Entries: {n}\n\n"
                        f"Review and approve with:\n"
                        f"/analyst approve {pending_id}\n\n"
                        f"Add a note first (optional):\n"
                        f"/analyst addnote {pending_id} Your note here\n\n"
                        f"Once approved the report is automatically sent to the client."
                    ),
                )
                await send_text(
                    f"Your weekly briefing has been prepared and sent to your advisor "
                    f"{analyst['name']} for a final review.\n\n"
                    f"You will receive it within {ANALYST_REVIEW_WINDOW_HOURS} hours, "
                    f"enriched with their personal insights."
                )
            except Exception as e:
                logger.error(f"Could not notify analyst {analyst_tid}: {e}")
                # Fall through to direct delivery if analyst notification fails
                await _send_report_to_chat(send_text, send_doc, report_text, pdf_path,
                                           restaurant, week_start)
            return  # Report will be delivered once analyst approves

    # Direct delivery (Solo tier or no analyst assigned)
    await _send_report_to_chat(send_text, send_doc, report_text, pdf_path,
                               restaurant, week_start)


async def _send_report_to_chat(send_text, send_doc, report_text, pdf_path,
                                restaurant, week_start):
    """Send the (possibly analyst-annotated) report text + PDF to the restaurant chat."""
    for chunk in _split_report_for_telegram(report_text):
        await send_text(chunk)
    with open(pdf_path, "rb") as f:
        await send_doc(f, os.path.basename(pdf_path),
                       f"Weekly briefing — {restaurant['name']} ({week_start})")


# ─── Scheduled jobs ───────────────────────────────────────────────────────────

async def job_weekly_report(context: ContextTypes.DEFAULT_TYPE):
    """Auto-send weekly reports to all active restaurants."""
    logger.info("Running scheduled weekly report…")
    for restaurant in get_all_restaurants():
        if not is_active(restaurant):
            continue
        try:
            chat_id = restaurant["telegram_group_id"]
            entries      = get_week_entries(restaurant["id"])
            prev_entries = get_prev_week_entries(restaurant["id"])

            async def send_text(text, _cid=chat_id):
                await context.bot.send_message(chat_id=_cid, text=text)

            async def send_doc(f, filename, caption, _cid=chat_id):
                await context.bot.send_document(
                    chat_id=_cid, document=f, filename=filename, caption=caption
                )

            await _deliver_weekly_report(
                send_text, send_doc, restaurant, entries, prev_entries,
                triggered_by_schedule=True, bot=context.bot,
            )
        except Exception as e:
            logger.error(f"Scheduled report failed for {restaurant.get('name')}: {e}")


async def job_flash_report(context: ContextTypes.DEFAULT_TYPE):
    """Daily evening flash report sent to all active restaurants."""
    logger.info("Running daily flash report…")
    today = datetime.now().strftime("%Y-%m-%d")
    for restaurant in get_all_restaurants():
        if not is_active(restaurant):
            continue
        try:
            chat_id = restaurant["telegram_group_id"]
            entries = get_entries_for_period(restaurant["id"], today, today)
            if not entries:
                continue  # No data today — don't spam

            entries_data = _build_entries_data(entries)
            summary      = generate_today_summary(entries_data, restaurant["name"])

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"END-OF-DAY FLASH — {restaurant['name']}\n"
                    f"{'─' * 34}\n\n"
                    f"{summary}\n\n"
                    f"({len(entries)} entries captured today)"
                ),
            )
        except Exception as e:
            logger.error(f"Flash report failed for {restaurant.get('name')}: {e}")


async def job_compliance_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Daily job: send Telegram alerts for compliance items due within 30 days."""
    items = get_compliance_items_due_soon(days=30)
    sent: dict = {}  # group_id → list of messages (avoid spamming same chat)

    for item in items:
        group_id = item["telegram_group_id"]
        due      = item["due_date"]
        days     = (datetime.fromisoformat(due) - datetime.now()).days

        if days < 0:
            icon = f"🔴 OVERDUE by {abs(days)} days"
        elif days == 0:
            icon = "🔴 DUE TODAY"
        elif days <= 7:
            icon = f"🔴 Due in {days} day{'s' if days != 1 else ''}"
        elif days <= 14:
            icon = f"⚠️  Due in {days} days"
        else:
            icon = f"📋 Due in {days} days"

        sent.setdefault(group_id, []).append(
            f"{icon}: {item['item_name']}  ({due})"
        )

    for group_id, messages in sent.items():
        try:
            await context.bot.send_message(
                chat_id=group_id,
                text=(
                    "COMPLIANCE REMINDER\n"
                    "─" * 28 + "\n\n"
                    + "\n".join(messages)
                    + "\n\nView all: /compliance"
                ),
            )
        except Exception as e:
            logger.error(f"Compliance reminder failed for {group_id}: {e}")


async def job_review_monitor(context: ContextTypes.DEFAULT_TYPE):
    """Hourly job: check each restaurant's Google listing for new negative reviews."""
    from google_reviews import get_new_reviews, format_review_alert, places_api_enabled
    if not places_api_enabled():
        return

    for restaurant in get_all_restaurants():
        if not is_active(restaurant):
            continue
        place_id = restaurant.get("google_place_id")
        if not place_id:
            continue

        since = int(restaurant.get("last_review_time") or 0)
        try:
            new_reviews = get_new_reviews(place_id, since_timestamp=since)
            if not new_reviews:
                continue

            # Update the timestamp to the newest review we've seen
            newest_ts = max(r.get("time", 0) for r in new_reviews)
            update_last_review_time(restaurant["id"], newest_ts)

            for review in new_reviews:
                alert = format_review_alert(review, restaurant["name"])
                await context.bot.send_message(
                    chat_id=restaurant["telegram_group_id"],
                    text=alert,
                )
        except Exception as e:
            logger.error(f"Review monitor failed for {restaurant.get('name')}: {e}")


async def job_ai_health(context: ContextTypes.DEFAULT_TYPE):
    """Periodic health check — alert admin if AI backend goes offline."""
    if not is_healthy():
        logger.warning("AI backend health check failed.")
        if ADMIN_TELEGRAM_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_TELEGRAM_ID,
                    text=(
                        "⚠️ Restaurant-IQ: AI backend not responding.\n\n"
                        "AI analysis will fail until the backend is restored.\n"
                        f"Backend: {backend_name()}"
                    ),
                )
            except Exception as e:
                logger.error(f"Could not send admin health alert: {e}")


# ─── Commands ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Restaurant-IQ — Your AI Chief of Staff\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "I turn your team's daily voice notes, invoices and texts into "
        "weekly financial intelligence — food cost %, GP margin, supplier "
        "alerts, and actionable priorities.\n\n"
        "SETUP\n"
        "  /register YourRestaurantName\n\n"
        "DAILY USE — just send anything:\n"
        "  🎙️ Voice note  → shift observation, issues, revenue\n"
        "  📸 Photo       → invoice or receipt\n"
        "  ✏️ Text        → any quick update\n\n"
        "FINANCIAL INTELLIGENCE\n"
        "  /metrics       KPI dashboard (food cost, covers, GP)\n"
        "  /labour        Wage bill & labour cost %\n"
        "  /today         End-of-day summary\n"
        "  /compare       This week vs last week\n"
        "  /benchmark     vs UK industry averages\n"
        "  /vat           Quarterly VAT estimate\n"
        "  /cashflow      30-day cash flow forecast\n"
        "  /overhead      All operating expenses (rent, energy, NI, compliance...)\n"
        "  /energy        Electricity & gas tracker + energy-saving tips\n"
        "  /grow          Revenue growth advisor + cost reduction quick wins\n"
        "  /noshow        Track booking no-shows and lost revenue\n\n"
        "OPERATIONS\n"
        "  /waste         Food waste log & cost\n"
        "  /cashup        Till reconciliation history\n"
        "  /allergens     Allergen incident log\n"
        "  /reliability   Supplier delivery reliability\n"
        "  /suppliers     Supplier price changes\n"
        "  /compliance    Equipment & certificate tracker\n"
        "  /menu          Menu profitability (4-box)\n\n"
        "REVIEWS\n"
        "  /setplace      Link your Google listing for review alerts\n\n"
        "REPORTS\n"
        "  /weeklyreport  Full briefing + PDF (auto Monday 08:00)\n"
        "  /history       Past reports\n"
        "  /export        Week's data as CSV\n\n"
        "ADVISOR\n"
        "  /findsupplier  Search UK supplier directory\n"
        "  /myanalyst     Your dedicated advisor (Managed/Enterprise)\n"
        "  /flivio        Flivio analytics dashboard\n\n"
        "SETTINGS\n"
        "  /targets       Set food cost %, restaurant type\n"
        "  /status        Subscription + entry summary\n"
        "  /upgrade       Plans and pricing\n\n"
        "14-day free trial — no card required."
    )


async def cmd_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /register YourRestaurantName\n\n"
            "Example: /register The Crown\n\n"
            "The person who runs /register becomes the owner account."
        )
        return

    name    = " ".join(context.args)
    chat_id = str(update.effective_chat.id)
    user    = update.effective_user
    user_id = str(user.id)

    register_restaurant(name, chat_id, user_id)
    restaurant = get_restaurant_by_group(chat_id)
    if restaurant:
        register_staff(restaurant["id"], user_id,
                       (user.first_name or "Owner"), "owner")

    days = trial_days_remaining(restaurant)
    await update.message.reply_text(
        f"✅ Registered: {name}\n"
        f"You are the owner.\n\n"
        f"🔔 Free trial: {days} days — no card required.\n\n"
        "WHAT TO DO NOW:\n"
        "1. Set your targets: /targets foodcost 30\n"
        "2. Tell your team to send voice notes and invoice photos to this group\n"
        "3. Run /weeklyreport any time for an on-demand briefing\n\n"
        "Weekly reports are auto-sent every Monday at 08:00.\n\n"
        "Try sending a voice note right now — even 10 seconds about today's shift. "
        "I'll show you what I extract from it."
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    entries = get_week_entries(restaurant["id"])
    today   = datetime.now()
    week_str = (today - timedelta(days=today.weekday())).strftime("%A %d %B")

    categories: dict = {}
    for e in entries:
        cat = e["category"] or "general"
        categories[cat] = categories.get(cat, 0) + 1

    cat_lines = "\n".join(f"  {k}: {v}" for k, v in sorted(categories.items()))
    if not cat_lines:
        cat_lines = "  None yet"

    sub_status = status_summary(restaurant)
    banner     = trial_banner(restaurant)

    await update.message.reply_text(
        f"STATUS — {restaurant['name']}\n"
        f"Week from: {week_str}\n"
        f"{'─' * 30}\n"
        f"Entries this week: {len(entries)}\n"
        f"By category:\n{cat_lines}\n\n"
        f"Subscription: {sub_status}{banner}"
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    today   = datetime.now().strftime("%Y-%m-%d")
    entries = get_entries_for_period(restaurant["id"], today, today)

    if not entries:
        await update.message.reply_text(
            "No entries captured today yet.\n"
            "Send voice notes, photos or text updates and then run /today again."
        )
        return

    await update.message.reply_text(f"Summarising {len(entries)} entries from today…")
    entries_data = _build_entries_data(entries)
    summary      = generate_today_summary(entries_data, restaurant["name"])

    await update.message.reply_text(
        f"TODAY — {restaurant['name']}  ({today})\n"
        f"{'─' * 34}\n\n"
        f"{summary}"
        + trial_banner(restaurant)
    )


async def cmd_weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    entries      = get_week_entries(restaurant["id"])
    prev_entries = get_prev_week_entries(restaurant["id"])

    async def send_text(text):
        await update.message.reply_text(text)

    async def send_doc(f, filename, caption):
        await update.message.reply_document(document=f, filename=filename, caption=caption)

    await _deliver_weekly_report(send_text, send_doc, restaurant, entries, prev_entries,
                                 bot=context.bot)


async def cmd_metrics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /metrics — KPI dashboard showing this week's food cost %, GP%, covers,
    revenue vs targets and previous week.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    entries      = get_week_entries(restaurant["id"])
    prev_entries = get_prev_week_entries(restaurant["id"])

    if not entries:
        await update.message.reply_text(
            "No entries this week yet.\n\n"
            "To see KPIs here, your team needs to:\n"
            '• Say "Revenue £3,200, 85 covers" in a voice note\n'
            "• Send invoice/receipt photos (auto-tracks food cost)\n\n"
            "Run /metrics again once data has been captured."
        )
        return

    entries_data = _build_entries_data(entries)
    prev_data    = _build_entries_data(prev_entries)
    current_kpis = build_kpis(entries_data)
    prev_kpis    = build_kpis(prev_data) if prev_data else None

    dashboard = format_kpi_dashboard(
        current_kpis, prev_kpis,
        restaurant["name"],
        float(restaurant["target_food_cost_pct"] or 30),
        restaurant["restaurant_type"] or "casual",
    )

    await update.message.reply_text(dashboard + trial_banner(restaurant))


async def cmd_compare(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /compare — week-on-week AI comparison (Growth tier+).
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return
    if not await _require_feature(update, restaurant, "compare"):
        return

    entries      = get_week_entries(restaurant["id"])
    prev_entries = get_prev_week_entries(restaurant["id"])

    if not entries:
        await update.message.reply_text("No entries this week yet. Send some data first.")
        return
    if not prev_entries:
        await update.message.reply_text(
            "No data from last week to compare against.\n"
            "The comparison will be available after you have two weeks of data."
        )
        return

    await update.message.reply_text("Comparing this week vs last week…")

    entries_data = _build_entries_data(entries)
    prev_data    = _build_entries_data(prev_entries)
    current_kpis = build_kpis(entries_data)
    prev_kpis    = build_kpis(prev_data)

    comparison = generate_comparison_report(
        entries_data, prev_data, current_kpis, prev_kpis, restaurant["name"],
        tier=get_tier(restaurant),
    )

    week_start, _ = _week_bounds()
    prev_start, _ = _week_bounds(offset_weeks=1)

    await update.message.reply_text(
        f"WEEK-ON-WEEK — {restaurant['name']}\n"
        f"This week:  {week_start}\n"
        f"Last week:  {prev_start}\n"
        f"{'─' * 34}\n\n"
        f"{comparison}"
        + trial_banner(restaurant)
    )


async def cmd_suppliers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /suppliers — supplier price changes detected from invoice photos.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return
    if not await _require_feature(update, restaurant, "suppliers"):
        return

    entries      = get_week_entries(restaurant["id"])
    entries_data = _build_entries_data(entries)

    current_prices  = extract_supplier_prices(entries_data)
    historic_prices = get_historic_supplier_prices(restaurant["id"])
    price_changes   = detect_price_changes(current_prices, historic_prices)

    changes_text = format_price_changes(price_changes)

    if not current_prices:
        await update.message.reply_text(
            "No supplier data captured this week.\n\n"
            "To track supplier prices: photograph invoice/delivery notes and send "
            "them to this group. I'll extract prices automatically."
        )
        return

    intel = generate_supplier_intelligence(price_changes, restaurant["name"])

    # List active suppliers
    supplier_list = "\n".join(f"  • {s}" for s in sorted(current_prices.keys()))

    await update.message.reply_text(
        f"SUPPLIER INTELLIGENCE — {restaurant['name']}\n"
        f"{'─' * 34}\n\n"
        f"ACTIVE SUPPLIERS THIS WEEK:\n{supplier_list}\n\n"
        f"PRICE CHANGES:\n{changes_text}\n\n"
        f"ANALYSIS:\n{intel}"
        + trial_banner(restaurant)
    )


async def cmd_benchmark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /benchmark — compare KPIs to London industry averages (Pro tier).
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return
    if not await _require_feature(update, restaurant, "benchmark"):
        return

    entries      = get_week_entries(restaurant["id"])
    entries_data = _build_entries_data(entries)
    current_kpis = build_kpis(entries_data)

    report = format_benchmark_comparison(
        current_kpis,
        restaurant["name"],
        restaurant["restaurant_type"] or "casual",
    )

    await update.message.reply_text(report + trial_banner(restaurant))


async def cmd_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /targets                    → show current targets
    /targets foodcost 30        → set food cost target to 30%
    /targets gp 70              → set GP target to 70%
    /targets type casual        → set restaurant type (casual/fine/qsr/cafe/gastropub)
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_feature(update, restaurant, "targets"):
        return

    VALID_TYPES = ("casual", "fine", "qsr", "cafe", "gastropub")

    if not context.args:
        # Show current targets
        fc  = restaurant["target_food_cost_pct"] or 30.0
        gp  = restaurant["target_gp_pct"] or 70.0
        rtype = restaurant["restaurant_type"] or "casual"
        await update.message.reply_text(
            f"TARGETS — {restaurant['name']}\n"
            f"{'─' * 30}\n"
            f"Food cost target: {fc}%\n"
            f"GP target:        {gp}%\n"
            f"Restaurant type:  {rtype}\n\n"
            "Change with:\n"
            "  /targets foodcost 30\n"
            "  /targets gp 70\n"
            "  /targets type casual|fine|qsr|cafe|gastropub"
        )
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "  /targets foodcost 30\n"
            "  /targets gp 70\n"
            "  /targets type casual"
        )
        return

    key, val = context.args[0].lower(), context.args[1].lower()

    if key == "foodcost":
        try:
            pct = float(val)
            assert 5 <= pct <= 80
        except (ValueError, AssertionError):
            await update.message.reply_text("Food cost must be a number between 5 and 80.")
            return
        update_restaurant_targets(restaurant["id"], food_cost_pct=pct)
        await update.message.reply_text(
            f"✅ Food cost target updated to {pct}%\n"
            f"You'll see this reflected in /metrics and your weekly report."
        )

    elif key == "gp":
        try:
            pct = float(val)
            assert 10 <= pct <= 95
        except (ValueError, AssertionError):
            await update.message.reply_text("GP must be a number between 10 and 95.")
            return
        update_restaurant_targets(restaurant["id"], gp_pct=pct)
        await update.message.reply_text(f"✅ GP target updated to {pct}%.")

    elif key == "type":
        if val not in VALID_TYPES:
            await update.message.reply_text(
                f"Restaurant type must be one of: {', '.join(VALID_TYPES)}"
            )
            return
        update_restaurant_targets(restaurant["id"], restaurant_type=val)
        await update.message.reply_text(
            f"✅ Restaurant type set to '{val}'.\n"
            "Benchmarks in /benchmark and /metrics will now reflect this category."
        )

    else:
        await update.message.reply_text(
            "Unknown setting. Use: foodcost, gp, or type"
        )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /history         → list last 4 weekly reports
    /history YYYY-MM-DD → retrieve specific week
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    if context.args:
        week_start = context.args[0]
        report = get_report_by_week(restaurant["id"], week_start)
        if not report:
            await update.message.reply_text(
                f"No report found for week starting {week_start}.\n"
                "Use /history to see available dates."
            )
            return

        header = f"REPORT — Week of {report['week_start']}\n{'═' * 34}\n\n"
        full   = header + (report["report_text"] or "")
        # Use existing splitter but substitute header
        for chunk in _split_report_for_telegram(report["report_text"] or ""):
            if "RESTAURANT-IQ WEEKLY BRIEFING" in chunk:
                chunk = header + chunk.split("\n\n", 1)[-1]
            await update.message.reply_text(chunk)
    else:
        reports = get_weekly_reports(restaurant["id"], limit=4)
        if not reports:
            await update.message.reply_text(
                "No reports yet.\nRun /weeklyreport to generate your first."
            )
            return
        lines = [f"REPORTS — {restaurant['name']}", ""]
        for r in reports:
            lines.append(f"  Week of {r['week_start']}  (saved {r['created_at'][:10]})")
        lines += ["", "Retrieve with: /history YYYY-MM-DD"]
        await update.message.reply_text("\n".join(lines))


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export this week's entries as a CSV file."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    entries = get_week_entries(restaurant["id"])
    if not entries:
        await update.message.reply_text("No entries this week to export.")
        return

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "time", "type", "category", "summary", "raw_text", "urgency",
                     "revenue", "covers", "waste_cost"])

    for e in entries:
        a = {}
        if e["structured_data"]:
            try:
                a = json.loads(e["structured_data"])
            except json.JSONDecodeError:
                pass
        writer.writerow([
            e["entry_date"], e["entry_time"], e["entry_type"],
            e["category"] or "general",
            a.get("summary", ""),
            e["raw_text"] or "",
            a.get("urgency", ""),
            a.get("revenue", ""),
            a.get("covers", ""),
            a.get("waste_cost", ""),
        ])

    week_start, _ = _week_bounds()
    safe_name = restaurant["name"].replace(" ", "_").replace("/", "-")
    filename  = f"{safe_name}_{week_start}_export.csv"

    await update.message.reply_document(
        document=io.BytesIO(buf.getvalue().encode("utf-8")),
        filename=filename,
        caption=f"Weekly data export — {restaurant['name']} ({week_start}). {len(entries)} entries.",
    )


async def cmd_deletedata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /deletedata       → delete entries >90 days (GDPR rolling retention, owner only)
    /deletedata all   → delete ALL entries for this restaurant (owner only)
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if not _is_owner(update, restaurant):
        await update.message.reply_text(
            "Only the registered owner can delete data.\n"
            "(The owner is the person who originally ran /register.)"
        )
        return

    if context.args and context.args[0].lower() == "all":
        count = delete_all_entries(restaurant["id"])
        await update.message.reply_text(
            f"All data deleted for {restaurant['name']}.\n"
            f"{count} entries permanently removed.\n\n"
            "Weekly report summaries are retained for reference."
        )
    else:
        count = delete_old_entries(restaurant["id"], days=90)
        await update.message.reply_text(
            f"{count} entries older than 90 days deleted from {restaurant['name']}.\n"
            "This keeps you GDPR-compliant (90-day rolling retention).\n\n"
            "Use /deletedata all to erase everything."
        )


async def cmd_labour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/labour — wage bill and labour cost % for the current week."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    entries      = get_week_entries(restaurant["id"])
    prev_entries = get_prev_week_entries(restaurant["id"])
    entries_data = _build_entries_data(entries)
    prev_data    = _build_entries_data(prev_entries) if prev_entries else None
    current_kpis = build_kpis(entries_data)
    prev_kpis    = build_kpis(prev_data) if prev_data else None

    target_labour = float(restaurant.get("target_labour_pct") or 30.0)
    dashboard = format_labour_dashboard(
        current_kpis, prev_kpis, restaurant["name"], target_labour
    )
    await update.message.reply_text(dashboard + trial_banner(restaurant))


async def cmd_waste(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/waste — food waste log and weekly total cost."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    entries      = get_week_entries(restaurant["id"])
    entries_data = _build_entries_data(entries)
    report = format_waste_report(entries_data, restaurant["name"])
    await update.message.reply_text(report + trial_banner(restaurant))


async def cmd_cashup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cashup — till reconciliation history for the current week."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    entries      = get_week_entries(restaurant["id"])
    entries_data = _build_entries_data(entries)
    report = format_cash_reconciliation(entries_data, restaurant["name"])
    await update.message.reply_text(report + trial_banner(restaurant))


async def cmd_allergens(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/allergens — allergen incident log for the current week."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    entries      = get_week_entries(restaurant["id"])
    entries_data = _build_entries_data(entries)
    report = format_allergen_log(entries_data, restaurant["name"])
    await update.message.reply_text(report + trial_banner(restaurant))


async def cmd_reliability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reliability — supplier delivery reliability over the last 30 days."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    # Pull 30 days of entries for reliability context
    today      = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    entries      = get_entries_for_period(restaurant["id"], start_date, today)
    entries_data = _build_entries_data(entries)
    report = format_supplier_reliability(entries_data, restaurant["name"])
    await update.message.reply_text(report + trial_banner(restaurant))


async def cmd_compliance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/compliance — equipment and certificate tracker.

    Subcommands:
      (no args)              Show upcoming items
      add <name> <YYYY-MM-DD> [notes]   Add a new item
      done <id>              Mark an item as completed
      delete <id>            Remove an item
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    args = context.args or []
    sub  = args[0].lower() if args else "list"

    if sub == "add":
        if len(args) < 3:
            await update.message.reply_text(
                "Usage: /compliance add \"Item Name\" YYYY-MM-DD\n\n"
                "Examples:\n"
                "  /compliance add Gas Safety Certificate 2026-09-15\n"
                "  /compliance add Deep Clean Due 2026-04-01\n"
                "  /compliance add Fire Extinguisher Service 2026-06-20"
            )
            return
        # Last arg before any notes is the date, everything before is the name
        date_str  = args[-1]
        item_name = " ".join(args[1:-1])
        try:
            from datetime import date
            date.fromisoformat(date_str)
        except ValueError:
            await update.message.reply_text(
                f"Date format must be YYYY-MM-DD, e.g. 2026-09-15\n"
                f"You entered: {date_str}"
            )
            return
        item_id = add_compliance_item(restaurant["id"], item_name, date_str)
        await update.message.reply_text(
            f"✅ Added: {item_name}\n"
            f"Due: {date_str}\n"
            f"Item ID: {item_id} (use /compliance done {item_id} when complete)"
        )

    elif sub == "done":
        if len(args) < 2 or not args[1].isdigit():
            await update.message.reply_text("Usage: /compliance done <id>\nExample: /compliance done 3")
            return
        complete_compliance_item(int(args[1]))
        await update.message.reply_text(f"✅ Item #{args[1]} marked as complete.")

    elif sub == "delete":
        if len(args) < 2 or not args[1].isdigit():
            await update.message.reply_text("Usage: /compliance delete <id>\nExample: /compliance delete 3")
            return
        delete_compliance_item(int(args[1]))
        await update.message.reply_text(f"Deleted item #{args[1]}.")

    else:
        items = get_compliance_items(restaurant["id"])
        lines = [f"COMPLIANCE TRACKER — {restaurant['name']}", "─" * 36, ""]

        if not items:
            lines.append("No compliance items added yet.")
            lines.append("")
            lines.append("Add items with:")
            lines.append("  /compliance add Gas Safety Certificate 2026-09-15")
            lines.append("  /compliance add Deep Clean Due 2026-04-01")
        else:
            today_str = datetime.now().strftime("%Y-%m-%d")
            for item in items:
                due   = item["due_date"]
                days  = (datetime.fromisoformat(due) - datetime.now()).days
                if days < 0:
                    icon = "🔴 OVERDUE"
                elif days <= 7:
                    icon = f"🔴 Due in {days}d"
                elif days <= 30:
                    icon = f"⚠️  Due in {days}d"
                else:
                    icon = f"✅  Due in {days}d"
                lines.append(f"{icon}  [{item['id']}] {item['item_name']}  ({due})")
                if item.get("notes"):
                    lines.append(f"       Note: {item['notes']}")

        lines.append("")
        lines.append("Commands: /compliance add <name> <date>  |  done <id>  |  delete <id>")
        await update.message.reply_text("\n".join(lines) + trial_banner(restaurant))


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/menu — menu profitability (4-box matrix).

    Subcommands:
      (no args)                             Show profitability analysis
      add <dish name> <food cost> <price>   Add / update a dish
      remove <dish name>                    Remove a dish
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    args = context.args or []
    sub  = args[0].lower() if args else "list"

    if sub == "add":
        if len(args) < 4:
            await update.message.reply_text(
                "Usage: /menu add <dish name> <food cost £> <selling price £>\n\n"
                "Examples:\n"
                "  /menu add Fish and Chips 4.20 14.50\n"
                "  /menu add Burger 3.80 13.00\n"
                "  /menu add Caesar Salad 2.10 9.50\n\n"
                "Food cost = what it costs you to make the dish.\n"
                "Selling price = what you charge the customer."
            )
            return
        try:
            selling_price = float(args[-1])
            food_cost     = float(args[-2])
            dish_name     = " ".join(args[1:-2])
        except ValueError:
            await update.message.reply_text(
                "Prices must be numbers.\n"
                "Example: /menu add Fish and Chips 4.20 14.50"
            )
            return
        if not dish_name:
            await update.message.reply_text("Please include a dish name.")
            return
        upsert_menu_item(restaurant["id"], dish_name, food_cost, selling_price)
        fc_pct = (food_cost / selling_price) * 100
        gp_pct = 100 - fc_pct
        await update.message.reply_text(
            f"✅ {dish_name} saved\n"
            f"Food cost: £{food_cost:.2f}  ({fc_pct:.0f}%)\n"
            f"Selling:   £{selling_price:.2f}\n"
            f"GP:        {gp_pct:.0f}%  {'✅' if fc_pct < 33 else '⚠️'}"
        )

    elif sub == "remove":
        if len(args) < 2:
            await update.message.reply_text("Usage: /menu remove <dish name>\nExample: /menu remove Caesar Salad")
            return
        dish_name = " ".join(args[1:])
        delete_menu_item(restaurant["id"], dish_name)
        await update.message.reply_text(f"Removed: {dish_name}")

    else:
        items  = get_menu_items(restaurant["id"])
        report = format_menu_profitability(items, restaurant["name"])
        await update.message.reply_text(report + trial_banner(restaurant))


async def cmd_vat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/vat — quarterly VAT estimate from captured revenue and cost data."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    # Use last 90 days (roughly a quarter) of entries
    today      = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    entries      = get_entries_for_period(restaurant["id"], start_date, today)
    entries_data = _build_entries_data(entries)

    report = format_vat_summary(entries_data, restaurant["name"], "last 90 days")
    await update.message.reply_text(report + trial_banner(restaurant))


async def cmd_cashflow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cashflow [balance] — 30-day cash flow forecast including all overheads.
    Usage: /cashflow 8400  (set current bank balance and see forecast)
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    # If user provided a balance, store it
    if context.args:
        try:
            balance = float(context.args[0].replace("£", "").replace(",", ""))
            update_known_balance(restaurant["id"], balance)
        except ValueError:
            await update.message.reply_text(
                "Please enter your current bank balance as a number.\n"
                "Example: /cashflow 8400"
            )
            return
    else:
        balance = restaurant.get("last_known_balance")

    # Get this week's KPIs + overhead estimate
    entries      = get_week_entries(restaurant["id"])
    entries_data = _build_entries_data(entries)
    kpis         = build_kpis(entries_data)
    weekly_oh    = get_weekly_overhead_estimate(restaurant["id"])

    report = format_cashflow_forecast(
        current_balance=balance,
        weekly_revenue=kpis.get("revenue", 0),
        weekly_food_cost=kpis.get("food_cost", 0),
        weekly_labour=kpis.get("labour_cost", 0),
        weekly_overheads=weekly_oh,
        restaurant_name=restaurant["name"],
    )
    await update.message.reply_text(report + trial_banner(restaurant))


async def cmd_overhead(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/overhead [type] [amount] [note] — Log or view operating expenses.

    View dashboard:
      /overhead

    Log an expense:
      /overhead electricity 450
      /overhead electricity 450 2800 kWh  (with units)
      /overhead rent 3200
      /overhead deliveroo 480 "March commission"

    Categories you can use:
      electricity, gas, oil
      rent, rates, insurance
      water, cleaning, packaging, repairs, uniforms, pest
      deliveroo, ubereats, just_eat, marketing
      card_fees, bank, accountant, loan
      pos, music, licence, software
      sundry, misc
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    args = context.args or []

    # No args → show dashboard
    if not args:
        summary      = get_overhead_summary(restaurant["id"], days=30)
        entries      = get_week_entries(restaurant["id"])
        entries_data = _build_entries_data(entries)
        kpis         = build_kpis(entries_data)
        report = format_overhead_dashboard(
            summary=summary,
            revenue=kpis.get("revenue", 0),
            food_cost=kpis.get("food_cost", 0),
            labour_cost=kpis.get("labour_cost", 0),
            restaurant_name=restaurant["name"],
            period_days=30,
        )
        await update.message.reply_text(report + trial_banner(restaurant))
        return

    # First arg is the expense type
    keyword = args[0].lower().strip()

    # Unknown keyword → accept as custom expense with a helpful prompt
    if keyword not in OVERHEAD_KEYWORD_MAP:
        if len(args) < 2:
            await update.message.reply_text(
                f"'{keyword}' is not a recognised expense type.\n\n"
                "Include the amount and we'll log it as a custom expense:\n"
                f"  /overhead {keyword} 150\n\n"
                "Or see the full list: /overhead"
            )
            return
        try:
            amount = float(args[1].replace("£", "").replace(",", ""))
        except ValueError:
            await update.message.reply_text("Amount must be a number. Example: /overhead repairs 250")
            return
        note_parts = args[2:]
        note = " ".join(note_parts).strip('"\'') if note_parts else None
        # Store as custom category so it still appears in dashboard
        subcategory = keyword.replace("_", " ").title()
        log_overhead(
            restaurant_id=restaurant["id"],
            category="custom",
            subcategory=subcategory,
            amount=amount,
            note=note,
        )
        await update.message.reply_text(
            f"✅ Logged as custom expense: {subcategory}\n"
            f"   Amount: £{amount:,.2f}\n\n"
            "To help us categorise this properly, reply:\n"
            "  /overhead [type] [amount]\n\n"
            "Where [type] is one of:\n"
            "  energy / occupancy / staffing / compliance\n"
            "  operations / marketing / finance / admin\n\n"
            "Or view your custom expenses in: /overhead"
        )
        return

    if len(args) < 2:
        await update.message.reply_text(
            f"Please include the amount.\n"
            f"Example: /overhead {keyword} 450"
        )
        return

    try:
        amount = float(args[1].replace("£", "").replace(",", ""))
    except ValueError:
        await update.message.reply_text(
            f"Amount must be a number. Example: /overhead {keyword} 450"
        )
        return

    category, subcategory = OVERHEAD_KEYWORD_MAP[keyword]

    # Optional: units (e.g. kWh or m³) as 3rd numeric arg
    units = None
    unit_type = None
    note_parts = args[2:]
    if note_parts:
        try:
            units = float(note_parts[0].replace(",", ""))
            if category == "energy":
                unit_type = "kWh" if "Electr" in subcategory else "m³"
            note_parts = note_parts[1:]
        except ValueError:
            pass  # not a number — treat as note text

    note = " ".join(note_parts).strip('"\'') if note_parts else None

    log_overhead(
        restaurant_id=restaurant["id"],
        category=category,
        subcategory=subcategory,
        amount=amount,
        note=note,
        units=units,
        unit_type=unit_type,
    )

    units_str = f"  ({units:,.0f} {unit_type})" if units and unit_type else ""
    note_str  = f"\n📝 Note: {note}" if note else ""
    await update.message.reply_text(
        f"✅ Logged: {subcategory}\n"
        f"   Amount: £{amount:,.2f}{units_str}{note_str}\n\n"
        f"View all overheads: /overhead\n"
        f"See cashflow impact: /cashflow"
    )


async def cmd_energy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/energy — Track electricity and gas bills, monitor costs, get saving tips.

    View energy dashboard:
      /energy

    Log a bill (amount only):
      /energy electricity 450
      /energy gas 380

    Log a bill with usage (amount + units):
      /energy electricity 450 2800   (£450 bill, 2800 kWh)
      /energy gas 380 1200           (£380 bill, 1200 m³)

    Get energy saving advice:
      /energy tips
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    args = context.args or []

    # /energy tips — show the saving advice
    if args and args[0].lower() in ("tips", "advice", "help", "save", "saving"):
        await update.message.reply_text(ENERGY_SAVING_TIPS)
        return

    # /energy electricity/gas [amount] [units] — log a bill
    energy_keywords = {"electricity", "electric", "gas", "oil"}
    if args and args[0].lower() in energy_keywords:
        keyword = args[0].lower()
        if len(args) < 2:
            sub = "electricity" if "electr" in keyword else keyword
            await update.message.reply_text(
                f"Please include the bill amount.\n"
                f"Example: /energy {sub} 450\n"
                f"With usage: /energy {sub} 450 2800"
            )
            return
        try:
            amount = float(args[1].replace("£", "").replace(",", ""))
        except ValueError:
            await update.message.reply_text("Amount must be a number. Example: /energy electricity 450")
            return

        category, subcategory = OVERHEAD_KEYWORD_MAP[keyword]
        units = None
        unit_type = None
        if len(args) >= 3:
            try:
                units = float(args[2].replace(",", ""))
                unit_type = "kWh" if "Electr" in subcategory else "m³"
            except ValueError:
                pass

        log_overhead(
            restaurant_id=restaurant["id"],
            category=category,
            subcategory=subcategory,
            amount=amount,
            units=units,
            unit_type=unit_type,
        )

        units_str = f"  ({units:,.0f} {unit_type})" if units and unit_type else ""
        tip = "\n\n💡 Tip: /energy tips for ways to reduce this bill." if amount > 300 else ""
        await update.message.reply_text(
            f"✅ Logged: {subcategory} bill\n"
            f"   Amount: £{amount:,.2f}{units_str}{tip}\n\n"
            f"See all energy data: /energy\n"
            f"See cashflow impact: /cashflow"
        )
        return

    # No args or unrecognised → show dashboard
    energy_logs = get_energy_logs(restaurant["id"], limit=12)
    entries      = get_week_entries(restaurant["id"])
    entries_data = _build_entries_data(entries)
    kpis         = build_kpis(entries_data)

    report = format_energy_dashboard(
        energy_logs=energy_logs,
        revenue=kpis.get("revenue", 0),
        restaurant_name=restaurant["name"],
    )
    await update.message.reply_text(report + trial_banner(restaurant))


async def cmd_grow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/grow — Personalised revenue growth and cost reduction advisor.

    Analyses your current KPIs, compares against UK benchmarks for your
    restaurant type, and gives your top 5 revenue opportunities with
    estimated £ impact, plus 5 cost reduction quick wins.

    Make sure your restaurant type is set correctly:
      /targets type casual|fine|qsr|cafe|gastropub
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    entries      = get_week_entries(restaurant["id"])
    entries_data = _build_entries_data(entries)
    kpis         = build_kpis(entries_data)
    overhead_summary = get_overhead_summary(restaurant["id"], days=30)

    report = format_revenue_growth_advisor(
        kpis=kpis,
        restaurant_type=restaurant.get("restaurant_type", "casual"),
        overhead_summary=overhead_summary,
        restaurant_name=restaurant["name"],
    )
    await update.message.reply_text(report + trial_banner(restaurant))


async def cmd_noshow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/noshow [count] [total_booked] — Track booking no-shows and their revenue cost.

    View no-show analysis:
      /noshow

    Log no-shows (today):
      /noshow 3           (3 covers didn't show up)
      /noshow 3 25        (3 no-shows from 25 booked covers)
      /noshow 5 40 "Saturday evening"

    The bot will calculate your weekly revenue loss and suggest how to reduce no-shows.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    args = context.args or []

    # No args → show analysis dashboard
    if not args:
        logs    = get_noshow_logs(restaurant["id"], days=90)
        summary = get_noshow_summary(restaurant["id"], days=90)
        entries      = get_week_entries(restaurant["id"])
        entries_data = _build_entries_data(entries)
        kpis         = build_kpis(entries_data)
        avg_spend    = kpis.get("avg_spend_per_head", 0)

        report = format_noshow_analysis(
            noshow_logs=logs,
            summary=summary,
            avg_spend=avg_spend,
            restaurant_name=restaurant["name"],
        )
        await update.message.reply_text(report + trial_banner(restaurant))
        return

    # Log no-shows
    try:
        covers_noshow = int(args[0])
    except ValueError:
        await update.message.reply_text(
            "Please enter the number of no-shows as a whole number.\n"
            "Example: /noshow 3\n"
            "Example: /noshow 3 25   (3 from 25 booked)"
        )
        return

    covers_booked = 0
    note_start = 1
    if len(args) >= 2:
        try:
            covers_booked = int(args[1])
            note_start = 2
        except ValueError:
            pass  # second arg is note text, not a number

    note_parts = args[note_start:]
    note = " ".join(note_parts).strip('"\'') if note_parts else None

    log_noshow(
        restaurant_id=restaurant["id"],
        covers_noshow=covers_noshow,
        covers_booked=covers_booked,
        note=note,
    )

    booked_str = f" (from {covers_booked} booked)" if covers_booked else ""
    # Quick revenue impact hint
    entries      = get_week_entries(restaurant["id"])
    entries_data = _build_entries_data(entries)
    kpis         = build_kpis(entries_data)
    avg_spend    = kpis.get("avg_spend_per_head", 0)
    lost_str = ""
    if avg_spend > 0 and covers_noshow > 0:
        lost = covers_noshow * avg_spend
        lost_str = f"\n   Revenue lost today: £{lost:,.0f}"

    await update.message.reply_text(
        f"✅ Logged: {covers_noshow} no-show{'s' if covers_noshow != 1 else ''}{booked_str}{lost_str}\n\n"
        "View no-show analysis: /noshow\n"
        "Reduce no-shows:  take card deposits at booking"
    )


async def cmd_setplace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setplace <Google Place ID> — link your Google Maps listing for review alerts."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not _is_owner(update, restaurant):
        await update.message.reply_text("Only the restaurant owner can set the Google Place ID.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /setplace <Google Place ID>\n\n"
            "How to find your Place ID:\n"
            "1. Go to Google Maps\n"
            "2. Search for your restaurant\n"
            "3. Click your listing → Share → copy the link\n"
            "4. The Place ID looks like: ChIJN1t_tDeuEmsRUsoyG83frY4\n\n"
            "Or visit: https://developers.google.com/maps/documentation/places/web-service/place-id"
        )
        return

    from google_reviews import places_api_enabled
    place_id = context.args[0].strip()
    set_google_place_id(restaurant["id"], place_id)

    if not places_api_enabled():
        await update.message.reply_text(
            f"Place ID saved: {place_id}\n\n"
            "⚠️ GOOGLE_API_KEY is not set, so review alerts won't work yet.\n"
            "Add your free Google API key in .env to enable review monitoring."
        )
        return

    # Test the Place ID works
    from google_reviews import get_recent_reviews
    reviews = get_recent_reviews(place_id)
    if reviews:
        rating = reviews[0].get("rating", "?")
        await update.message.reply_text(
            f"✅ Google listing linked!\n\n"
            f"Found {len(reviews)} recent review(s). Most recent rating: {rating}⭐\n\n"
            f"You'll now receive instant alerts whenever a new review is posted."
        )
    else:
        await update.message.reply_text(
            f"Place ID saved. No reviews found yet (or the Place ID may be incorrect).\n"
            f"Place ID: {place_id}\n\n"
            f"If this is wrong, run /setplace again with the correct ID."
        )


async def cmd_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show subscription status and upgrade options with real payment links if Stripe is set up."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    from stripe_payments import stripe_enabled, create_checkout_url
    from subscription import TIERS

    if not stripe_enabled():
        # Stripe not configured yet — show the static text prompt
        await update.message.reply_text(upgrade_prompt(restaurant))
        return

    # Build a message with real Stripe payment links for each plan
    owner_id = str(update.effective_user.id)
    lines = [upgrade_prompt(restaurant), "\n─\n💳 *Choose your plan to pay now:*\n"]

    for tier, info in TIERS.items():
        try:
            url = create_checkout_url(tier, restaurant["id"], owner_id)
            lines.append(
                f"• [{info['name']} — £{info['price_gbp']}/month]({url})"
            )
        except Exception as e:
            logger.error(f"Stripe checkout error for tier {tier}: {e}")
            lines.append(f"• {info['name']} — £{info['price_gbp']}/month (payment link unavailable)")

    lines.append("\n_Links expire after 24 hours. Type /upgrade again for a fresh link._")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


async def cmd_myanalyst(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /myanalyst — show the assigned advisor's details and contact info.
    Available on Managed and Enterprise tiers.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    if not has_human_advisor(restaurant):
        await update.message.reply_text(
            "Your current plan (Solo) is bot-only.\n\n"
            "Upgrade to Managed or Enterprise to get a dedicated advisor "
            "who reviews your weekly reports and checks in regularly.\n\n"
            + upgrade_prompt(restaurant)
        )
        return

    analyst = get_analyst_for_restaurant(restaurant["id"])
    if not analyst:
        await update.message.reply_text(
            "Your advisor is being assigned — you'll hear from us within 24 hours.\n\n"
            "If you've just signed up, welcome! We'll be in touch shortly."
        )
        return

    tier = get_tier(restaurant)
    hours_week = 2 if tier == "managed" else 4
    hours_used = get_hours_this_week(restaurant["id"], analyst["id"])
    hours_left = max(0, hours_week - hours_used)

    await update.message.reply_text(
        f"YOUR ADVISOR — {restaurant['name']}\n"
        f"{'─' * 34}\n\n"
        f"Name:    {analyst['name']}\n"
        f"Email:   {analyst.get('email') or 'Via Telegram'}\n\n"
        f"Hours included this week:  {hours_week}h\n"
        f"Hours used this week:      {hours_used:.1f}h\n"
        f"Hours remaining:           {hours_left:.1f}h\n\n"
        f"Your advisor reviews every weekly report before it reaches you, "
        f"adds personal observations, and flags anything that needs attention.\n\n"
        f"To send them a message, just reply to any report or email directly."
        + trial_banner(restaurant)
    )


async def cmd_findsupplier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /findsupplier [category or name] — search the UK supplier directory.
    Solo/Managed see top 3 results; Enterprise sees full list with details.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    query = " ".join(context.args).strip() if context.args else ""
    if not query:
        await update.message.reply_text(
            "Usage: /findsupplier [category or name]\n\n"
            "Examples:\n"
            "  /findsupplier meat\n"
            "  /findsupplier fish London\n"
            "  /findsupplier dairy\n"
            "  /findsupplier produce nationwide\n\n"
            "Categories: meat, fish, produce, dairy, dry goods, beverages, packaging"
        )
        return

    # Parse optional region from last word if recognised
    parts  = query.split()
    region = None
    known_regions = {"london", "nationwide", "north", "south", "midlands", "scotland", "wales"}
    if parts[-1].lower() in known_regions:
        region = parts[-1].lower()
        query  = " ".join(parts[:-1])

    suppliers = search_suppliers(query, region=region)
    is_enterprise = has_feature(restaurant, "supplier_db")

    result = format_supplier_results(suppliers, max_show=10 if is_enterprise else 3,
                                     is_enterprise=is_enterprise)

    await update.message.reply_text(
        f"SUPPLIER SEARCH — {query.title()}\n"
        f"{'─' * 34}\n\n"
        f"{result}"
        + trial_banner(restaurant)
    )


async def cmd_flivio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /flivio — link to the Flivio analytics dashboard (Managed/Enterprise).
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    if not has_feature(restaurant, "flivio_access"):
        await update.message.reply_text(
            "Flivio is included in Managed and Enterprise plans.\n\n"
            "Flivio gives you rich dashboards — recipe costing, delivery platform "
            "analysis, and financial forecasting — all linked to your Restaurant-IQ data.\n\n"
            + upgrade_prompt(restaurant)
        )
        return

    flivio_id  = restaurant.get("flivio_restaurant_id")
    status     = get_integration_status()
    dash_url   = get_flivio_dashboard_url(flivio_id)

    await update.message.reply_text(
        f"FLIVIO ANALYTICS — {restaurant['name']}\n"
        f"{'─' * 34}\n\n"
        f"Integration: {status}\n\n"
        f"Dashboard:  {dash_url}\n\n"
        f"Your weekly entries are automatically exported to Flivio each week. "
        f"Log in to view recipe costing, delivery analysis, and financial forecasts.\n\n"
        f"Need help connecting your account? Contact your advisor or email support."
        + trial_banner(restaurant)
    )


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return the sender's Telegram user ID — useful for admin/analyst setup."""
    user = update.effective_user
    await update.message.reply_text(
        f"Your Telegram User ID is:\n\n`{user.id}`\n\n"
        "Copy this number and paste it into your `.env` file as `ADMIN_TELEGRAM_ID`.",
        parse_mode="Markdown",
    )


async def cmd_setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all Telegram info for this bot and a .env configuration checklist."""
    import os
    from config import (
        GROQ_API_KEY, GOOGLE_API_KEY, ANTHROPIC_API_KEY,
        STRIPE_SECRET_KEY, FLIVIO_API_URL,
    )

    user = update.effective_user
    bot_user = await context.bot.get_me()

    def tick(val):
        return "✅" if val else "❌"

    token_set   = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN != "your_telegram_bot_token_here")
    admin_set   = bool(ADMIN_TELEGRAM_ID)
    groq_set    = bool(GROQ_API_KEY)
    google_set  = bool(GOOGLE_API_KEY)
    claude_set  = bool(ANTHROPIC_API_KEY)
    stripe_set  = bool(STRIPE_SECRET_KEY)
    flivio_set  = bool(FLIVIO_API_URL)

    lines = [
        "🤖 *Restaurant-IQ Bot — Setup Checklist*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "📋 *YOUR TELEGRAM INFO*",
        f"  Your User ID:  `{user.id}`",
        f"  Your Username: @{user.username or 'not set'}",
        f"  Bot Username:  @{bot_user.username}",
        f"  Bot ID:        `{bot_user.id}`",
        "",
        "🔑 *REQUIRED*",
        f"  {tick(token_set)} TELEGRAM\\_BOT\\_TOKEN",
        f"      → Get from @BotFather → /mybots → API Token",
        f"  {tick(admin_set)} ADMIN\\_TELEGRAM\\_ID",
        f"      → Your User ID above: `{user.id}`",
        "",
        "🤖 *FREE AI BACKENDS (pick at least one)*",
        f"  {tick(groq_set)} GROQ\\_API\\_KEY",
        f"      → console.groq.com/keys  (free, no card)",
        f"  {tick(google_set)} GOOGLE\\_API\\_KEY",
        f"      → aistudio.google.com/apikey  (free, no card)",
        "",
        "💳 *PAID / OPTIONAL*",
        f"  {tick(claude_set)} ANTHROPIC\\_API\\_KEY  (Enterprise tier only)",
        f"  {tick(stripe_set)} STRIPE\\_SECRET\\_KEY  (needed for billing)",
        f"  {tick(flivio_set)} FLIVIO\\_API\\_URL     (dashboard integration)",
        "",
        "📝 *NEXT STEPS*",
        "  1. Open your `.env` file",
        "  2. Fill in any ❌ items above",
        "  3. Restart the bot",
        "",
        "Run /myid at any time to re-check your User ID.",
    ]

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_analyst(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /analyst <subcommand> — internal commands for the Restaurant-IQ advisory team.

    Subcommands:
      clients              List your assigned clients and health scores
      review               List reports awaiting your approval
      approve <id>         Approve and deliver a pending report
      addnote <id> <text>  Add a note to a pending report before approving
      note <name> <text>   Log an observation for a client (by partial name)
      hours <name> <h>     Log hours spent on a client this week
      assign <name> <tid>  Assign yourself (or another analyst) to a client
      digest               Your weekly client digest
    """
    user    = update.effective_user
    user_id = str(user.id)

    # Only authorised analysts can use this command
    if user_id not in [str(tid) for tid in ANALYST_TELEGRAM_IDS]:
        await update.message.reply_text(
            "This command is for the Restaurant-IQ advisory team only."
        )
        return

    analyst = get_analyst_by_telegram_id(user_id)
    if not analyst:
        await update.message.reply_text(
            "You're not registered as an analyst yet.\n"
            "Ask an admin to add you via the database or contact support."
        )
        return

    sub = context.args[0].lower() if context.args else "help"
    args = context.args[1:] if len(context.args) > 1 else []

    # ── clients ──────────────────────────────────────────────────────────────
    if sub == "clients":
        clients = get_clients_for_analyst(analyst["id"])
        if not clients:
            await update.message.reply_text("You have no assigned clients yet.")
            return
        lines = [f"YOUR CLIENTS ({len(clients)})\n{'─' * 30}"]
        for c in clients:
            entries = get_week_entries(c["id"])
            score, label, _ = client_health_score(c["id"], len(entries),
                                                   float(c.get("target_food_cost_pct") or 30))
            lines.append(f"• {c['name']}  [{label} {score}]  entries this week: {len(entries)}")
        await update.message.reply_text("\n".join(lines))

    # ── review ───────────────────────────────────────────────────────────────
    elif sub == "review":
        pending = get_pending_reports_for_analyst(analyst["id"])
        if not pending:
            await update.message.reply_text("No reports awaiting your review.")
            return
        lines = [f"PENDING REPORTS ({len(pending)})\n{'─' * 30}"]
        for p in pending:
            lines.append(
                f"ID {p['id']} — {p['restaurant_name']}  (week {p['week_start']})\n"
                f"  /analyst approve {p['id']}\n"
                f"  /analyst addnote {p['id']} Your note here"
            )
        await update.message.reply_text("\n".join(lines))

    # ── addnote <pending_id> <text> ──────────────────────────────────────────
    elif sub == "addnote":
        if len(args) < 2:
            await update.message.reply_text("Usage: /analyst addnote <report_id> <your note>")
            return
        try:
            pending_id = int(args[0])
        except ValueError:
            await update.message.reply_text("Report ID must be a number.")
            return
        note_text = " ".join(args[1:])
        pending = get_pending_report(pending_id)
        if not pending:
            await update.message.reply_text(f"Report {pending_id} not found.")
            return
        set_pending_report_note(pending_id, note_text)
        await update.message.reply_text(
            f"Note saved for report {pending_id}.\n"
            f"Approve with: /analyst approve {pending_id}"
        )

    # ── approve <pending_id> ─────────────────────────────────────────────────
    elif sub == "approve":
        if not args:
            await update.message.reply_text("Usage: /analyst approve <report_id>")
            return
        try:
            pending_id = int(args[0])
        except ValueError:
            await update.message.reply_text("Report ID must be a number.")
            return
        pending = get_pending_report(pending_id)
        if not pending:
            await update.message.reply_text(f"Report {pending_id} not found.")
            return

        approved = approve_report(pending_id, pending.get("analyst_note") or "")

        # Rebuild final report with analyst note appended
        final_report = approved["ai_report_text"]
        if approved.get("analyst_note"):
            final_report += "\n\n" + format_analyst_note_for_report(
                approved["analyst_note"], analyst["name"]
            )

        # Look up the restaurant to get its chat ID
        rest = get_restaurant_by_id(approved["restaurant_id"])
        if rest and context.bot:
            chat_id = rest["telegram_group_id"]
            week_start = approved["week_start"]

            async def send_t(text, _cid=chat_id):
                await context.bot.send_message(chat_id=_cid, text=text)

            async def send_d(f, filename, caption, _cid=chat_id):
                await context.bot.send_document(
                    chat_id=_cid, document=f, filename=filename, caption=caption
                )

            for chunk in _split_report_for_telegram(final_report):
                await send_t(chunk)

            pdf_path = approved.get("pdf_path")
            if pdf_path and os.path.exists(pdf_path):
                with open(pdf_path, "rb") as f:
                    await send_d(f, os.path.basename(pdf_path),
                                 f"Weekly briefing — {rest['name']} ({week_start})")

            await update.message.reply_text(
                f"Report {pending_id} approved and delivered to {rest['name']}."
            )
            log_analyst_hours(rest["id"], analyst["id"], 0.25,
                              f"Report review & approval — week {week_start}")
        else:
            await update.message.reply_text("Could not find restaurant to deliver report.")

    # ── note <partial_name> <text> ────────────────────────────────────────────
    elif sub == "note":
        if len(args) < 2:
            await update.message.reply_text("Usage: /analyst note <client_name> <observation>")
            return
        name_query = args[0].lower()
        note_text  = " ".join(args[1:])
        clients = get_clients_for_analyst(analyst["id"])
        matched = [c for c in clients if name_query in c["name"].lower()]
        if not matched:
            await update.message.reply_text(
                f"No client matching '{args[0]}' found in your list.\n"
                "Use /analyst clients to see your full list."
            )
            return
        client = matched[0]
        add_analyst_note(client["id"], analyst["id"], note_text, note_type="observation")
        await update.message.reply_text(
            f"Note logged for {client['name']}:\n\"{note_text}\""
        )

    # ── hours <partial_name> <hours> ─────────────────────────────────────────
    elif sub == "hours":
        if len(args) < 2:
            await update.message.reply_text("Usage: /analyst hours <client_name> <hours_spent>")
            return
        name_query = args[0].lower()
        try:
            h = float(args[1])
        except ValueError:
            await update.message.reply_text("Hours must be a number, e.g. /analyst hours Crown 1.5")
            return
        clients = get_clients_for_analyst(analyst["id"])
        matched = [c for c in clients if name_query in c["name"].lower()]
        if not matched:
            await update.message.reply_text(f"No client matching '{args[0]}' found.")
            return
        client = matched[0]
        log_analyst_hours(client["id"], analyst["id"], h, "Manual log")
        used = get_hours_this_week(client["id"], analyst["id"])
        await update.message.reply_text(
            f"Logged {h}h for {client['name']}.\n"
            f"Total this week: {used:.1f}h"
        )

    # ── digest ────────────────────────────────────────────────────────────────
    elif sub == "digest":
        clients = get_clients_for_analyst(analyst["id"])
        hours_summary = get_hours_summary_for_analyst(analyst["id"])
        digest = format_analyst_digest(analyst["id"], clients, hours_summary)
        await update.message.reply_text(digest)

    else:
        await update.message.reply_text(
            "ANALYST COMMANDS\n"
            "─────────────────────────────\n"
            "/analyst clients          Your clients + health\n"
            "/analyst review           Reports awaiting approval\n"
            "/analyst addnote <id>     Add note to a report\n"
            "/analyst approve <id>     Approve + deliver report\n"
            "/analyst note <name> ...  Log client observation\n"
            "/analyst hours <name> <h> Log hours on a client\n"
            "/analyst digest           Weekly client digest\n"
        )


# ─── Message handlers ─────────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    staff = _ensure_staff(restaurant["id"], update.effective_user)
    voice = update.message.voice or update.message.audio
    file  = await voice.get_file()
    path  = os.path.join(VOICE_DIR, f"{voice.file_unique_id}.ogg")
    await file.download_to_drive(path)

    await update.message.reply_text(
        f"Voice note received, {update.effective_user.first_name}. Transcribing…"
    )

    try:
        text = transcribe_audio(path)
        if not text:
            await update.message.reply_text(
                "Could not transcribe — audio may be too short or unclear."
            )
            return

        analysis = analyze_text_entry(text, restaurant["name"])
        save_entry(restaurant["id"], staff["id"], "voice", text,
                   json.dumps(analysis), analysis.get("category", "general"))

        icon    = URGENCY_ICONS.get(analysis.get("urgency", "low"), "⚪")
        summary = analysis.get("summary", text[:100])

        await update.message.reply_text(
            f"Captured ✓\n"
            f'"{text[:220]}"\n\n'
            f"Category: {analysis.get('category', 'general')}\n"
            f"Summary:  {summary}\n"
            f"Urgency:  {icon} {analysis.get('urgency', 'low')}"
            + trial_banner(restaurant)
        )
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    staff  = _ensure_staff(restaurant["id"], update.effective_user)
    photo  = update.message.photo[-1]
    file   = await photo.get_file()
    path   = os.path.join(PHOTO_DIR, f"{photo.file_unique_id}.jpg")
    await file.download_to_drive(path)

    await update.message.reply_text("Photo received. Reading it now…")

    try:
        analysis = analyze_invoice_photo(path, restaurant["name"])

        raw_text = (
            f"Photo: {analysis.get('supplier_name', 'unknown supplier')} — "
            f"{analysis.get('summary', 'document captured')}"
        )
        save_entry(restaurant["id"], staff["id"], "photo", raw_text,
                   json.dumps(analysis), analysis.get("category", "cost"))

        # Save supplier prices for intelligence tracking
        supplier = analysis.get("supplier_name", "").strip()
        if supplier and analysis.get("items"):
            prices = {
                supplier: {
                    item["name"]: {"unit_price": item.get("unit_price"), "unit": item.get("unit", "")}
                    for item in analysis.get("items", [])
                    if item.get("name") and item.get("unit_price")
                }
            }
            if prices[supplier]:
                save_supplier_prices(restaurant["id"], prices, datetime.now().strftime("%Y-%m-%d"))

        total_str = f"£{analysis['total_amount']:.2f}" if analysis.get("total_amount") else "Not found"

        await update.message.reply_text(
            f"Invoice / Receipt Captured ✓\n"
            f"Supplier: {analysis.get('supplier_name') or 'Unknown'}\n"
            f"Total:    {total_str}\n"
            f"Summary:  {analysis.get('summary', 'Document logged')}\n\n"
            "Prices saved for supplier intelligence tracking."
            + trial_banner(restaurant)
        )
    finally:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return
    if not await _require_active(update, restaurant):
        return

    staff    = _ensure_staff(restaurant["id"], update.effective_user)
    text     = update.message.text
    analysis = analyze_text_entry(text, restaurant["name"])

    save_entry(restaurant["id"], staff["id"], "text", text,
               json.dumps(analysis), analysis.get("category", "general"))

    icon    = URGENCY_ICONS.get(analysis.get("urgency", "low"), "⚪")
    summary = analysis.get("summary", text[:80])
    await update.message.reply_text(
        f"Noted {icon} ({analysis.get('category', 'general')}): {summary}"
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    init_db()

    # Startup AI backend check
    if is_healthy():
        logger.info(f"AI backend ready: {backend_name()}")
    else:
        logger.warning(
            f"⚠️  AI backend NOT reachable: {backend_name()}\n"
            "Analysis will fail until the backend is available."
        )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("register",     cmd_register))
    app.add_handler(CommandHandler("status",       cmd_status))
    app.add_handler(CommandHandler("today",        cmd_today))
    app.add_handler(CommandHandler("weeklyreport", cmd_weekly_report))
    app.add_handler(CommandHandler("metrics",      cmd_metrics))
    app.add_handler(CommandHandler("compare",      cmd_compare))
    app.add_handler(CommandHandler("suppliers",    cmd_suppliers))
    app.add_handler(CommandHandler("benchmark",    cmd_benchmark))
    app.add_handler(CommandHandler("targets",      cmd_targets))
    app.add_handler(CommandHandler("history",      cmd_history))
    app.add_handler(CommandHandler("export",       cmd_export))
    app.add_handler(CommandHandler("deletedata",   cmd_deletedata))
    app.add_handler(CommandHandler("upgrade",      cmd_upgrade))
    app.add_handler(CommandHandler("myanalyst",    cmd_myanalyst))
    app.add_handler(CommandHandler("findsupplier", cmd_findsupplier))
    app.add_handler(CommandHandler("flivio",       cmd_flivio))
    app.add_handler(CommandHandler("myid",         cmd_myid))
    app.add_handler(CommandHandler("setup",        cmd_setup))
    app.add_handler(CommandHandler("analyst",      cmd_analyst))
    # New feature commands
    app.add_handler(CommandHandler("labour",       cmd_labour))
    app.add_handler(CommandHandler("waste",        cmd_waste))
    app.add_handler(CommandHandler("cashup",       cmd_cashup))
    app.add_handler(CommandHandler("allergens",    cmd_allergens))
    app.add_handler(CommandHandler("reliability",  cmd_reliability))
    app.add_handler(CommandHandler("compliance",   cmd_compliance))
    app.add_handler(CommandHandler("menu",         cmd_menu))
    app.add_handler(CommandHandler("vat",          cmd_vat))
    app.add_handler(CommandHandler("cashflow",     cmd_cashflow))
    app.add_handler(CommandHandler("overhead",     cmd_overhead))
    app.add_handler(CommandHandler("energy",       cmd_energy))
    app.add_handler(CommandHandler("grow",         cmd_grow))
    app.add_handler(CommandHandler("noshow",       cmd_noshow))
    app.add_handler(CommandHandler("setplace",     cmd_setplace))

    # Messages — voice before text
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO,                  handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Scheduled jobs (requires python-telegram-bot[job-queue])
    if app.job_queue:
        # AI health check every 60 seconds
        app.job_queue.run_repeating(job_ai_health, interval=60, first=30)

        # Weekly full report
        try:
            h, m = map(int, REPORT_TIME.split(":"))
            app.job_queue.run_daily(
                job_weekly_report,
                time=dtime(hour=h, minute=m),
                days=(_DAYS_MAP.get(REPORT_DAY, 0),),
                name="weekly_report",
            )
            logger.info(f"Weekly report scheduled: {REPORT_DAY.capitalize()} {REPORT_TIME}")
        except Exception as e:
            logger.error(f"Failed to schedule weekly report: {e}")

        # Daily flash report
        try:
            fh, fm = map(int, FLASH_REPORT_TIME.split(":"))
            app.job_queue.run_daily(
                job_flash_report,
                time=dtime(hour=fh, minute=fm),
                name="flash_report",
            )
            logger.info(f"Daily flash report scheduled: {FLASH_REPORT_TIME}")
        except Exception as e:
            logger.error(f"Failed to schedule flash report: {e}")

        # Daily compliance reminders at 09:00
        app.job_queue.run_daily(
            job_compliance_reminders,
            time=dtime(hour=9, minute=0),
            name="compliance_reminders",
        )
        logger.info("Daily compliance reminders scheduled: 09:00")

        # Hourly Google review monitor
        app.job_queue.run_repeating(
            job_review_monitor,
            interval=3600,
            first=120,  # First check 2 minutes after startup
            name="review_monitor",
        )
        logger.info("Google review monitor scheduled: every hour")
    else:
        logger.warning(
            "Job queue not available. Install python-telegram-bot[job-queue] "
            "for scheduled reports and health monitoring."
        )

    # Start Stripe webhook server if Stripe is configured
    from stripe_payments import stripe_enabled
    if stripe_enabled():
        from stripe_webhook import start_webhook_server
        start_webhook_server()
    else:
        logger.info("Stripe not configured — webhook server not started. Set STRIPE_SECRET_KEY to enable payments.")

    logger.info("Restaurant-IQ Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
