"""
Restaurant-IQ Telegram Bot
--------------------------
Entry point. Run with:  python bot.py

Commands:
  /start         — welcome message and usage guide
  /register      — register this Telegram group as a restaurant
  /status        — show entries captured this week
  /today         — quick end-of-day summary (today's entries only)
  /weeklyreport  — generate and send the weekly intelligence briefing + PDF
  /history       — list past reports; /history YYYY-MM-DD to retrieve one
  /export        — export this week's entries as a CSV file
  /deletedata    — delete entries >90 days old (owner only, GDPR)
  /deletedata all — delete ALL entries for this restaurant (owner only)

Message types:
  Voice notes  → transcribed by Whisper → analysed by fast text model
  Photos       → analysed by vision model (invoice/receipt reading)
  Text         → analysed by fast text model
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

from analyzer import (
    analyze_invoice_photo,
    analyze_text_entry,
    generate_today_summary,
    generate_weekly_report,
    is_ollama_healthy,
)
from config import (
    ADMIN_TELEGRAM_ID,
    REPORT_DAY,
    REPORT_TIME,
    TELEGRAM_BOT_TOKEN,
)
from database import (
    delete_all_entries,
    delete_old_entries,
    get_all_restaurants,
    get_entries_for_period,
    get_or_register_staff,
    get_report_by_week,
    get_restaurant_by_group,
    get_week_entries,
    get_weekly_reports,
    init_db,
    register_restaurant,
    register_staff,
    save_entry,
    save_weekly_report,
)
from report_generator import generate_pdf_report
from transcriber import transcribe_audio

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

REPORTS_DIR = "reports"
VOICE_DIR = "voice_files"
PHOTO_DIR = "photo_files"

URGENCY_ICONS = {"high": "🔴", "medium": "🟡", "low": "🟢"}

# Scheduled report: day name → PTB JobQueue day integer (0 = Monday … 6 = Sunday)
_DAYS_MAP = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

for _d in [REPORTS_DIR, VOICE_DIR, PHOTO_DIR]:
    os.makedirs(_d, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_staff(restaurant_id: int, user) -> dict:
    """Get or auto-register a staff member. Single INSERT OR IGNORE + SELECT."""
    name = user.first_name or str(user.id)
    return get_or_register_staff(restaurant_id, str(user.id), name)


async def _require_restaurant(update: Update):
    """Return the restaurant for this chat, or reply with an error and return None."""
    chat_id = str(update.effective_chat.id)
    restaurant = get_restaurant_by_group(chat_id)
    if not restaurant:
        await update.message.reply_text(
            "This group isn't registered yet.\n"
            "Use /register YourRestaurantName to get started."
        )
        return None
    return restaurant


def _is_owner(update: Update, restaurant) -> bool:
    """Return True if the sender is the registered owner of this restaurant."""
    return str(update.effective_user.id) == str(restaurant["owner_telegram_id"])


def _build_entries_data(entries) -> list:
    """Convert DB rows into the dict format expected by analyzer functions."""
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
    return entries_data


def _split_report_for_telegram(report_text: str) -> list[str]:
    """
    Split a long report into chunks that fit Telegram's 4096-char limit.
    Splits at '## ' section boundaries where possible, otherwise at line boundaries.
    """
    header = f"RESTAURANT-IQ WEEKLY BRIEFING\n{'=' * 34}\n\n"
    max_chunk = 3900  # leave headroom

    if len(header) + len(report_text) <= max_chunk:
        return [header + report_text]

    chunks = []
    current = header

    for line in report_text.split("\n"):
        # Start a new chunk at a section heading when current chunk is long enough
        if line.startswith("## ") and len(current) > len(header) and len(current) + len(line) > max_chunk:
            chunks.append(current.rstrip())
            current = line + "\n"
        elif len(current) + len(line) + 1 > max_chunk:
            # Hard split when a single chunk overflows
            chunks.append(current.rstrip())
            current = line + "\n"
        else:
            current += line + "\n"

    if current.strip():
        chunks.append(current.rstrip())

    return chunks or [header + report_text[:max_chunk]]


async def _deliver_weekly_report(bot_or_update, chat_id: str,
                                  restaurant, entries, triggered_by_schedule: bool = False):
    """
    Core report-generation logic shared by /weeklyreport and the scheduled job.
    `bot_or_update` is either an Update (for command) or a Bot (for scheduled job).
    """
    is_command = hasattr(bot_or_update, "message")

    async def send(text):
        if is_command:
            await bot_or_update.message.reply_text(text)
        else:
            await bot_or_update.send_message(chat_id=chat_id, text=text)

    async def send_doc(path, filename, caption):
        with open(path, "rb") as f:
            if is_command:
                await bot_or_update.message.reply_document(
                    document=f, filename=filename, caption=caption
                )
            else:
                await bot_or_update.send_document(
                    chat_id=chat_id, document=f, filename=filename, caption=caption
                )

    if not entries:
        if triggered_by_schedule:
            return  # Don't spam empty groups on auto-schedule
        await send(
            "No data captured this week yet.\n"
            "Send voice notes, photos or text updates first, then run /weeklyreport again."
        )
        return

    intro = (
        f"Good morning! Generating your weekly briefing from {len(entries)} entries...\n"
        "This may take 1-2 minutes."
        if triggered_by_schedule
        else f"Generating weekly briefing from {len(entries)} entries...\n"
             "This may take 1-2 minutes while the AI analyses everything."
    )
    await send(intro)

    entries_data = _build_entries_data(entries)
    report_text = generate_weekly_report(entries_data, restaurant["name"])

    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    week_end = today.strftime("%Y-%m-%d")

    save_weekly_report(restaurant["id"], week_start, week_end, report_text)

    safe_name = restaurant["name"].replace(" ", "_").replace("/", "-")
    pdf_path = os.path.join(REPORTS_DIR, f"{safe_name}_{week_start}.pdf")
    generate_pdf_report(report_text, restaurant["name"], week_start, week_end, pdf_path)

    # Send text (split at section boundaries if long)
    for chunk in _split_report_for_telegram(report_text):
        await send(chunk)

    # Send PDF
    await send_doc(
        pdf_path,
        os.path.basename(pdf_path),
        f"Weekly briefing for {restaurant['name']} — {week_start}",
    )


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

async def job_weekly_report(context: ContextTypes.DEFAULT_TYPE):
    """Automatically send weekly reports to all registered restaurants."""
    logger.info("Running scheduled weekly report job…")
    restaurants = get_all_restaurants()
    for restaurant in restaurants:
        try:
            chat_id = restaurant["telegram_group_id"]
            entries = get_week_entries(restaurant["id"])
            await _deliver_weekly_report(
                context.bot, chat_id, restaurant, entries, triggered_by_schedule=True
            )
        except Exception as e:
            logger.error(f"Scheduled report failed for {restaurant.get('name')}: {e}")


async def job_ollama_health(context: ContextTypes.DEFAULT_TYPE):
    """Periodic check — alert admin if Ollama goes offline."""
    if not is_ollama_healthy():
        logger.warning("Ollama health check failed — not reachable.")
        if ADMIN_TELEGRAM_ID:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_TELEGRAM_ID,
                    text=(
                        "⚠️ Restaurant-IQ Alert\n\n"
                        "Ollama is not responding. AI features (voice analysis, invoice reading, "
                        "weekly reports) will not work until Ollama is restarted.\n\n"
                        "Fix: run `ollama serve` on the host machine."
                    ),
                )
            except Exception as e:
                logger.error(f"Could not send admin health alert: {e}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to Restaurant-IQ!\n\n"
        "I capture operational data from your team and turn it into weekly intelligence briefings.\n\n"
        "SETUP:\n"
        "  /register YourRestaurantName — Register this group\n\n"
        "DAILY USE (just send me anything):\n"
        "  Voice note — Shift update, observations, issues\n"
        "  Photo       — Invoice, receipt, delivery note\n"
        "  Text        — Any quick update\n\n"
        "REPORTS:\n"
        "  /today        — Quick end-of-day summary\n"
        "  /weeklyreport — Full weekly briefing + PDF (also auto-sent Monday 08:00)\n"
        "  /status       — Entry count breakdown for this week\n"
        "  /history      — List recent reports; /history YYYY-MM-DD for a specific week\n\n"
        "DATA:\n"
        "  /export       — Download this week's entries as a CSV\n"
        "  /deletedata   — Delete entries older than 90 days (owner only)\n\n"
        "Every message from any team member in this group is captured and analysed automatically."
    )


async def cmd_register(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /register YourRestaurantName\nExample: /register Joe's Bistro"
        )
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
        f"Try sending a voice note about today's shift!\n\n"
        f"Tip: Weekly reports are auto-sent every Monday at 08:00. "
        f"Use /weeklyreport any time for an on-demand briefing."
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

    await update.message.reply_text(
        f"Restaurant-IQ — {restaurant['name']}\n"
        f"Week from: {week_start_str}\n\n"
        f"Entries captured: {len(entries)}\n"
        f"By category:\n{cat_summary}\n\n"
        f"Keep the data coming — voice notes, photos and texts all count!"
    )


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick end-of-day summary for today's entries only. No PDF."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    entries = get_entries_for_period(restaurant["id"], today_str, today_str)

    if not entries:
        await update.message.reply_text(
            "No entries captured today yet.\n"
            "Send voice notes, photos or text updates and then try /today again."
        )
        return

    await update.message.reply_text(
        f"Summarising {len(entries)} entries from today…"
    )

    entries_data = _build_entries_data(entries)
    summary = generate_today_summary(entries_data, restaurant["name"])
    await update.message.reply_text(
        f"TODAY — {restaurant['name']} ({today_str})\n"
        f"{'─' * 34}\n\n"
        f"{summary}"
    )


async def cmd_weekly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    entries = get_week_entries(restaurant["id"])
    chat_id = str(update.effective_chat.id)
    await _deliver_weekly_report(update, chat_id, restaurant, entries)


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /history         — list last 4 weekly reports
    /history YYYY-MM-DD — retrieve and send that specific week's report
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if context.args:
        week_start = context.args[0]
        report = get_report_by_week(restaurant["id"], week_start)
        if not report:
            await update.message.reply_text(
                f"No report found for week starting {week_start}.\n"
                "Use /history to see available reports."
            )
            return

        header = f"REPORT — Week of {report['week_start']}\n{'=' * 34}\n\n"
        full = header + (report["report_text"] or "")
        for chunk in _split_report_for_telegram(report["report_text"] or ""):
            # Replace the auto-generated header with the archive header for first chunk
            if chunk.startswith("RESTAURANT-IQ WEEKLY BRIEFING"):
                chunk = header + chunk[chunk.index("\n\n") + 2:]
            await update.message.reply_text(chunk)
    else:
        reports = get_weekly_reports(restaurant["id"], limit=4)
        if not reports:
            await update.message.reply_text(
                "No weekly reports generated yet.\n"
                "Run /weeklyreport to create your first."
            )
            return

        lines = [f"Recent reports for {restaurant['name']}:", ""]
        for r in reports:
            lines.append(f"  Week of {r['week_start']}  (saved {r['created_at'][:10]})")
        lines += ["", "Use /history YYYY-MM-DD to retrieve a specific report."]
        await update.message.reply_text("\n".join(lines))


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export this week's entries as a CSV file attachment."""
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    entries = get_week_entries(restaurant["id"])
    if not entries:
        await update.message.reply_text(
            "No entries this week to export. "
            "Send some voice notes, photos or texts first."
        )
        return

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "time", "type", "category", "summary", "raw_text", "urgency"])

    for e in entries:
        summary = ""
        urgency = ""
        if e["structured_data"]:
            try:
                a = json.loads(e["structured_data"])
                summary = a.get("summary", "")
                urgency = a.get("urgency", "")
            except json.JSONDecodeError:
                pass

        writer.writerow([
            e["entry_date"],
            e["entry_time"],
            e["entry_type"],
            e["category"] or "general",
            summary,
            e["raw_text"] or "",
            urgency,
        ])

    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    safe_name = restaurant["name"].replace(" ", "_").replace("/", "-")
    filename = f"{safe_name}_{week_start}_export.csv"

    csv_bytes = output.getvalue().encode("utf-8")
    await update.message.reply_document(
        document=io.BytesIO(csv_bytes),
        filename=filename,
        caption=f"Weekly data export — {restaurant['name']} ({week_start}). {len(entries)} entries.",
    )


async def cmd_deletedata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /deletedata       — delete entries older than 90 days (GDPR rolling retention)
    /deletedata all   — delete ALL entries for this restaurant
    Owner only.
    """
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    if not _is_owner(update, restaurant):
        await update.message.reply_text(
            "Only the registered owner can delete data.\n"
            "The owner is the person who originally ran /register."
        )
        return

    if context.args and context.args[0].lower() == "all":
        count = delete_all_entries(restaurant["id"])
        await update.message.reply_text(
            f"All data deleted for {restaurant['name']}.\n"
            f"{count} entries permanently removed.\n\n"
            "Note: weekly report summaries are retained for reference."
        )
    else:
        count = delete_old_entries(restaurant["id"], days=90)
        await update.message.reply_text(
            f"{count} entries older than 90 days deleted from {restaurant['name']}.\n"
            "Recent data is preserved. This keeps you GDPR-compliant.\n\n"
            "Use /deletedata all to remove everything."
        )


# ---------------------------------------------------------------------------
# Message handlers
# ---------------------------------------------------------------------------

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
        f"Got your voice note, {update.effective_user.first_name}. Transcribing…"
    )

    try:
        text = transcribe_audio(file_path)
        if not text:
            await update.message.reply_text(
                "Could not transcribe — audio may be too short or unclear."
            )
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
            f"Urgency: {icon} {urgency}"
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

    await update.message.reply_text("Got the photo. Reading it now…")

    try:
        analysis = analyze_invoice_photo(file_path, restaurant["name"])
        raw_text = (
            f"Photo from {update.effective_user.first_name}: "
            f"{analysis.get('summary', 'Document captured')}"
        )
        save_entry(
            restaurant["id"],
            staff["id"],
            "photo",
            raw_text,
            json.dumps(analysis),
            analysis.get("category", "cost"),
        )

        supplier = analysis.get("supplier_name") or "Unknown"
        total = analysis.get("total_amount")
        total_str = f"£{total:.2f}" if total else "Not found"

        await update.message.reply_text(
            f"Invoice / Receipt Captured:\n"
            f"Supplier: {supplier}\n"
            f"Total: {total_str}\n"
            f"Summary: {analysis.get('summary', 'Document logged')}\n\n"
            "Added to your weekly briefing."
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

    summary = analysis.get("summary", text[:80])
    await update.message.reply_text(
        f"Noted ({analysis.get('category', 'general')}): {summary}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    init_db()

    # Startup Ollama health check
    if is_ollama_healthy():
        logger.info("Ollama is reachable — AI features ready.")
    else:
        logger.warning(
            "⚠️  Ollama is NOT reachable. "
            "Analysis will fail until Ollama is started. Run: ollama serve"
        )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("register", cmd_register))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("weeklyreport", cmd_weekly_report))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("deletedata", cmd_deletedata))

    # Messages — voice must come before text
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Scheduled jobs (requires python-telegram-bot[job-queue])
    if app.job_queue:
        # Ollama health check every 60 seconds
        app.job_queue.run_repeating(job_ollama_health, interval=60, first=30)

        # Weekly report — default Monday 08:00 local time
        try:
            hour, minute = map(int, REPORT_TIME.split(":"))
            report_day_int = _DAYS_MAP.get(REPORT_DAY, 0)
            app.job_queue.run_daily(
                job_weekly_report,
                time=dtime(hour=hour, minute=minute),
                days=(report_day_int,),
                name="weekly_report",
            )
            logger.info(
                f"Scheduled weekly report: {REPORT_DAY.capitalize()} at {REPORT_TIME} "
                f"(day index {report_day_int})"
            )
        except Exception as e:
            logger.error(f"Failed to schedule weekly report job: {e}")
    else:
        logger.warning(
            "Job queue not available. Install python-telegram-bot[job-queue] "
            "to enable scheduled weekly reports and health monitoring."
        )

    logger.info("Restaurant-IQ Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
