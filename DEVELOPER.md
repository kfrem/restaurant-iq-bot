# Developer Handover — Restaurant-IQ Bot

This document covers the full technical context for the next developer picking up this project: what is built, how it works, what is outstanding, and recommended implementation approach.

---

## Project Purpose

Restaurant-IQ is a Telegram bot for independent restaurant owners. Staff send operational updates throughout the day (voice notes after a busy shift, photos of invoices, quick text observations). The bot accumulates this data and produces a weekly AI intelligence briefing — structured insights about revenue, waste, costs, staff issues, and supplier anomalies.

**Key constraint:** All AI processing runs locally via Ollama. No data is sent to external APIs. This is a deliberate privacy/cost decision.

---

## Current State (Phase 1 Complete)

### What works today

- `/register`, `/start`, `/status`, `/weeklyreport` commands
- Voice note → Whisper transcription → Ollama structured extraction
- Invoice/receipt photo → Ollama vision model → supplier + line item extraction
- Text message → Ollama fast model → categorised entry
- SQLite persistence (restaurants, staff, daily entries, weekly reports)
- Weekly briefing generation (markdown narrative via Ollama)
- Branded A4 PDF report (ReportLab)
- Windows one-click installer (`install.py`)
- Multi-restaurant support (each Telegram group = separate restaurant)

### What is not yet built (Phase 2)

These are listed in priority order — tackle them in this sequence.

---

## Outstanding Work

### 1. Ollama Health Check on Startup
**Priority: High — blocks usability if Ollama is down**

Currently, if Ollama isn't running when the bot starts, the first message from staff will silently fail (the error is only printed to the server console, not sent back to Telegram).

**What to build:**
- At bot startup (in `main()` in `bot.py`), call `ollama.list()` and check it returns successfully
- If it fails, log a clear warning: `"WARNING: Ollama not reachable. Analysis will fail until Ollama is started."`
- Optionally, send a message to a configured admin Telegram ID if `ADMIN_TELEGRAM_ID` is set in `.env`
- Check every 60 seconds in a background task and send an alert if it goes down mid-session

**Files to touch:** `bot.py`, `config.py` (add `ADMIN_TELEGRAM_ID`)

---

### 2. Scheduled Weekly Reports
**Priority: High — owners forget to run `/weeklyreport`**

Currently, owners must manually run `/weeklyreport`. Most won't remember consistently.

**What to build:**
- Every Monday at 08:00 local time, auto-generate and send the weekly report to every registered restaurant group
- Add `REPORT_DAY` (default: `monday`) and `REPORT_TIME` (default: `08:00`) to `.env`
- Use `python-telegram-bot`'s built-in `JobQueue` — it is already available in the `Application` object, no extra library needed
- The job should call the same logic as `cmd_weekly_report` but triggered by the scheduler, not a user command

**Implementation sketch:**
```python
# In main(), after app is built:
app.job_queue.run_daily(
    auto_weekly_report,
    time=datetime.time(hour=8, minute=0),
    days=(0,),          # 0 = Monday
)

async def auto_weekly_report(context: ContextTypes.DEFAULT_TYPE):
    """Send weekly report to all registered restaurants."""
    restaurants = get_all_restaurants()   # add this to database.py
    for restaurant in restaurants:
        entries = get_week_entries(restaurant["id"])
        if not entries:
            continue
        # ... same logic as cmd_weekly_report but using restaurant["telegram_group_id"]
        # as the chat_id instead of update.effective_chat.id
        await context.bot.send_message(chat_id=restaurant["telegram_group_id"], text=report)
```

**New database function needed:**
```python
def get_all_restaurants() -> list:
    with _db() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM restaurants")
        return c.fetchall()
```

**Files to touch:** `bot.py`, `database.py`, `config.py`

---

### 3. `/today` End-of-Day Summary
**Priority: Medium — quick value add**

A lightweight command that gives the owner a same-day summary rather than making them wait for Monday's full report.

**What to build:**
- `/today` command: summarise today's entries only (not the whole week)
- Uses the fast text model (`OLLAMA_TEXT_MODEL`) not the large report model
- Returns a short (5–10 line) plain-text summary, no PDF
- Format: total entries today, top category, any high-urgency flags, one action item

**Files to touch:** `bot.py`, `analyzer.py` (add `generate_daily_summary(entries, restaurant_name)`)

---

### 4. `/history` — Retrieve Past Reports
**Priority: Medium**

Owners sometimes need last week's report or a report from a specific date.

**What to build:**
- `/history` — lists the last 4 weekly reports with dates
- `/history 2024-01-08` — sends the specific report for that week
- Reports are already saved in `weekly_reports` table; this is a read-only query + send

**Files to touch:** `bot.py`, `database.py` (add `get_weekly_reports(restaurant_id, limit)` and `get_report_by_week(restaurant_id, week_start)`)

---

### 5. Rebuild `install.py` After Any Code Changes
**Priority: Medium — the Windows installer is currently stale**

`install.py` embeds all source files as base64 so Windows users can bootstrap from a single file. It was generated from an earlier version and does **not** reflect the current code.

**What to do:**
Run this from inside the `restaurant-iq-bot/` directory:

```python
# regenerate_installer.py — run this after any code change
import base64, os

files = [
    'config.py', 'database.py', 'transcriber.py', 'analyzer.py',
    'report_generator.py', 'bot.py', '.env.example',
    'requirements.txt', 'setup_windows.bat',
]

# ... encode each file and write install.py
# See the existing install.py for the output format
```

Consider making this a `make` target or a pre-commit hook so it stays in sync automatically.

---

### 6. `/deletedata` — GDPR Compliance
**Priority: Medium (required before any commercial use)**

Staff voice notes and message text are personal data. There must be a way to delete it.

**What to build:**
- `/deletedata` (owner only) — deletes all daily entries older than 90 days
- `/deletedata all` — deletes all entries for this restaurant
- Add `owner_telegram_id` check before executing (only the person who ran `/register` can delete)

---

### 7. Export to CSV
**Priority: Low**

Some owners will want to import the weekly data into Excel or accounting software.

**What to build:**
- `/export` command — generates a CSV of all entries for the current week
- Columns: date, time, type, category, summary, raw_text, urgency
- Send as a file attachment (same as the PDF, using `reply_document`)

---

### 8. Multi-Language Support
**Priority: Low**

Some London restaurant teams communicate in languages other than English.

**What to build:**
- Pass `language=None` to `model.transcribe()` in `transcriber.py` to enable auto-detect (Whisper supports this)
- Add detected language to the entry metadata
- The Ollama prompts are in English; consider adding a `REPORT_LANGUAGE` env var

---

## Architecture Notes

### Adding a New Bot Command

1. Write the handler function in `bot.py`:
   ```python
   async def cmd_mycommand(update: Update, context: ContextTypes.DEFAULT_TYPE):
       restaurant = await _require_restaurant(update)
       if not restaurant:
           return
       # ... your logic
   ```
2. Register it in `main()`:
   ```python
   app.add_handler(CommandHandler("mycommand", cmd_mycommand))
   ```
3. Update the `/start` message to document the new command

### Adding a Database Query

All DB access goes through `database.py`. Never call sqlite3 directly from `bot.py`.

```python
def get_something(restaurant_id: int):
    with _db() as conn:           # _db() is a @contextmanager — always use it
        c = conn.cursor()
        c.execute("SELECT ...", (restaurant_id,))
        return c.fetchall()
```

### Changing an AI Prompt

Prompts live in `analyzer.py`. When changing a prompt:
- Keep the JSON schema in the prompt identical to what callers expect
- The `_extract_json()` helper tolerates model preamble/postamble — it finds the first `{...}` block
- Always test with `temperature=0.1` for structured output

### PDF Report Format

The PDF is generated in `report_generator.py`. The report text coming from Ollama uses markdown-style formatting:
- `## Heading` → section heading
- `- item` or `* item` → bullet point
- `1.` `2.` etc. → numbered list
- `---` → horizontal rule

To change the visual style, edit the `ParagraphStyle` definitions in `_build_styles()`. Colours are defined as hex constants at the top of the file.

---

## Known Limitations

| Limitation | Notes |
|---|---|
| SQLite is single-writer | Fine for a single bot instance. If you ever run multiple bot workers (e.g. for scale), switch to PostgreSQL |
| No authentication on commands | Any Telegram user in a registered group can trigger `/weeklyreport`. Add an owner-check if needed |
| `qwen3-vl:30b` requires ~20 GB RAM | On machines with less RAM, substitute `qwen2.5-vl:7b` — same capability, smaller footprint |
| Voice files are deleted after transcription | This is intentional (privacy + disk space). If you need audio archives, remove the `finally: os.remove()` blocks in `bot.py` |
| Weekly report splits at 4000 chars | Telegram's limit is 4096 chars. Long reports are cut with `[continued in PDF...]`. A cleaner fix is to split at section boundaries |

---

## Environment Variables Reference

| Variable | Default | Notes |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Required |
| `OLLAMA_MODEL` | `qwen3-vl:30b` | Vision + report model |
| `OLLAMA_TEXT_MODEL` | `gemma3:4b` | Fast analysis model |
| `WHISPER_MODEL_SIZE` | `base` | `tiny` fastest, `medium` most accurate |
| `DB_PATH` | `restaurant_iq.db` | Change to an absolute path for production |
| `ADMIN_TELEGRAM_ID` | — | To add: Telegram user ID to receive health alerts |
| `REPORT_DAY` | — | To add: Day to auto-send reports (e.g. `monday`) |
| `REPORT_TIME` | — | To add: Time to auto-send reports (e.g. `08:00`) |

---

## Running in Production (Linux Server / VPS)

For production deployment (rather than a developer's laptop):

```bash
# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
nano .env   # set token, set DB_PATH to an absolute path

# Run as a systemd service (recommended over screen/tmux)
# Create /etc/systemd/system/restaurant-iq.service:
[Unit]
Description=Restaurant-IQ Telegram Bot
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/restaurant-iq-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10
EnvironmentFile=/home/ubuntu/restaurant-iq-bot/.env

[Install]
WantedBy=multi-user.target

# Enable and start
sudo systemctl enable restaurant-iq
sudo systemctl start restaurant-iq
sudo journalctl -u restaurant-iq -f   # follow logs
```

**Ollama on a server:** Run `ollama serve` as a separate systemd service. The bot connects to `http://localhost:11434` by default (Ollama's default). If Ollama is on a different machine, set the `OLLAMA_HOST` environment variable.

---

## Testing

There are currently no automated tests. Before adding features, consider adding:

- Unit tests for `_extract_json()` in `analyzer.py` — it's the most fragile function (parses AI output)
- Unit tests for `database.py` — use an in-memory SQLite database (`DB_PATH=":memory:"`)
- A `pytest` fixture that creates a fresh DB and tears it down after each test

Recommended: `pytest` + `pytest-asyncio` for the async Telegram handlers.

---

## Repo Structure

```
restaurant-iq-bot/
├── README.md               User-facing documentation
├── DEVELOPER.md            This file
├── bot.py                  Entry point + Telegram handlers
├── config.py               Env var loading
├── database.py             SQLite layer
├── transcriber.py          Whisper voice transcription
├── analyzer.py             Ollama AI analysis
├── report_generator.py     PDF generation
├── requirements.txt        Python dependencies
├── .env.example            Env var template
├── install.py              Windows one-click bootstrapper
└── setup_windows.bat       Windows pip installer
```
