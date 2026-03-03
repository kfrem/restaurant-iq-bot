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
  /benchmark      Compare KPIs to London industry benchmarks (Pro)
  /export         Download this week's entries as CSV
  /deletedata     Delete entries >90 days (GDPR, owner only)
  /upgrade        View plans and subscription status

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
    FLASH_REPORT_TIME,
    REPORT_DAY,
    REPORT_TIME,
    TELEGRAM_BOT_TOKEN,
)
from database import (
    delete_all_entries,
    delete_old_entries,
    get_all_restaurants,
    get_entries_for_period,
    get_historic_supplier_prices,
    get_or_register_staff,
    get_prev_week_entries,
    get_report_by_week,
    get_restaurant_by_group,
    get_supplier_prices,
    get_week_entries,
    get_weekly_reports,
    init_db,
    register_restaurant,
    register_staff,
    save_entry,
    save_supplier_prices,
    save_weekly_report,
    update_restaurant_targets,
)
from intelligence import (
    build_kpis,
    detect_price_changes,
    extract_supplier_prices,
    format_benchmark_comparison,
    format_kpi_dashboard,
    format_price_changes,
)
from report_generator import generate_pdf_report
from subscription import (
    has_feature,
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
                                  prev_entries=None, triggered_by_schedule=False):
    """
    Core weekly report logic — shared between /weeklyreport and the scheduled job.
    `send_text` and `send_doc` are async callables so this works for both contexts.
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

    # Send text (section-split if long)
    for chunk in _split_report_for_telegram(report_text):
        await send_text(chunk)

    # Send PDF
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
                triggered_by_schedule=True,
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
        "INTELLIGENCE\n"
        "  /metrics       KPI dashboard (food cost, covers, GP)\n"
        "  /today         End-of-day summary\n"
        "  /compare       This week vs last week\n"
        "  /suppliers     Supplier price changes\n"
        "  /benchmark     vs London industry averages\n\n"
        "REPORTS\n"
        "  /weeklyreport  Full briefing + PDF (auto Monday 08:00)\n"
        "  /history       Past reports\n"
        "  /export        Week's data as CSV\n\n"
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

    await _deliver_weekly_report(send_text, send_doc, restaurant, entries, prev_entries)


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
        entries_data, prev_data, current_kpis, prev_kpis, restaurant["name"]
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


async def cmd_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show subscription status and upgrade options."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    await update.message.reply_text(upgrade_prompt(restaurant))


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
    else:
        logger.warning(
            "Job queue not available. Install python-telegram-bot[job-queue] "
            "for scheduled reports and health monitoring."
        )

    logger.info("Restaurant-IQ Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
