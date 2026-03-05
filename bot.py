"""
Restaurant-IQ Telegram Bot
--------------------------
Entry point. Run with:  python bot.py

Handles:
  - /start     — welcome message
  - /register  — register this Telegram group as a restaurant
  - /status    — show entries captured this week
  - /weeklyreport — generate and send the weekly intelligence briefing

Message types:
  - Voice notes  → transcribed by Whisper → analysed by Qwen
  - Photos       → analysed by Qwen vision (invoice/receipt reading)
  - Text         → analysed by Qwen fast model
"""

import os
import json
import logging
from datetime import datetime, timedelta

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
    get_week_entries,
    save_weekly_report,
)
from transcriber import transcribe_audio
from analyzer import analyze_text_entry, analyze_invoice_photo, generate_weekly_report
from model_router import get_tier_status
from report_generator import generate_pdf_report

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
        await update.message.reply_text("Please /register this group first.")
        return None
    return restaurant


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

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
        "REPORTS:\n"
        "  /weeklyreport — Generate this week's briefing (PDF included)\n"
        "  /status       — See how many entries captured this week\n\n"
        "Every message from any team member in this group is captured and analysed."
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
        f"AI Tier: {tier['label']}\n"
        f"Restaurants registered: {tier['count']}\n"
        f"{next_info}\n\n"
        f"Keep the data coming — voice notes, photos and texts all count!"
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

    # Build entries list for the report generator
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

    report_text = generate_weekly_report(entries_data, restaurant["name"])

    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    week_end = today.strftime("%Y-%m-%d")

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
        # Split at a sensible boundary
        await update.message.reply_text(full_message[:4000] + "\n\n[continued in PDF...]")

    # Send PDF
    with open(pdf_path, "rb") as pdf_file:
        await update.message.reply_document(
            document=pdf_file,
            filename=os.path.basename(pdf_path),
            caption=f"Weekly briefing for {restaurant['name']} — {week_start}",
        )


# ---------------------------------------------------------------------------
# Message handlers
# ---------------------------------------------------------------------------

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    restaurant = await _require_restaurant(update)
    if not restaurant:
        return

    staff = _ensure_staff(restaurant["id"], update.effective_user)

    # Download the voice file
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

    # Download largest photo resolution
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
            f"Added to your weekly briefing."
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

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("register", cmd_register))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("weeklyreport", cmd_weekly_report))

    # Messages — order matters: voice before text
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Restaurant-IQ Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
