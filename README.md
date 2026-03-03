# Restaurant-IQ Bot

A Telegram bot that captures operational data from restaurant staff — voice notes, invoice photos, and text updates — and turns it into a weekly AI-generated intelligence briefing with a branded PDF report.

All AI runs **locally** on your machine via [Ollama](https://ollama.com). No data leaves your network.

---

## What It Does

Staff in a Telegram group simply send:

| Input | What happens |
|---|---|
| **Voice note** | Transcribed by Whisper → analysed for revenue, covers, waste, issues |
| **Photo** (invoice / receipt) | Read by vision model → supplier name, total, line items extracted |
| **Text message** | Analysed for category, summary, urgency |

At the end of the week, the owner runs `/weeklyreport` and receives:
- A structured text briefing directly in Telegram
- A branded A4 PDF attached to the same message

---

## Architecture

```
bot.py                  Telegram bot entry point (python-telegram-bot)
├── transcriber.py      Voice → text  (faster-whisper, runs on CPU)
├── analyzer.py         Text/photo → structured JSON  (Ollama: gemma3:4b + qwen3-vl:30b)
├── report_generator.py Weekly text → branded PDF  (ReportLab)
├── database.py         SQLite persistence  (no ORM, plain sqlite3)
└── config.py           Environment variable loading  (python-dotenv)
```

### AI Models (via Ollama)

| Model | Use | Why |
|---|---|---|
| `gemma3:4b` | Text entry analysis | Fast; good structured JSON extraction |
| `qwen3-vl:30b` | Invoice photo reading + weekly report narrative | Vision capability; best quality |
| Whisper `base` | Voice transcription | Runs on CPU; no API cost |

### Database (SQLite)

Four tables:

```
restaurants          — one row per registered Telegram group
staff                — auto-registered when a member first sends a message
daily_entries        — every voice note / photo / text captured
weekly_reports       — saved report text for each week
```

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Windows 10/11 or macOS | Linux also works |
| Python 3.11+ | [python.org](https://python.org) |
| [Ollama](https://ollama.com) | Must be running before starting the bot |
| Telegram bot token | Create via [@BotFather](https://t.me/BotFather) |

### Pull the required Ollama models (one-time, ~20 GB total)

```bash
ollama pull gemma3:4b
ollama pull qwen3-vl:30b
```

> The `qwen3-vl:30b` model requires ~20 GB RAM. If your machine has less, swap it for `qwen2.5-vl:7b` in `.env` — quality will be lower but it will run.

---

## Quick Start (Windows)

1. Create a folder: `C:\RestaurantIQ`
2. Download `install.py` from this repo into that folder
3. Open Command Prompt and run:
   ```
   cd C:\RestaurantIQ
   python install.py
   ```
4. When Notepad opens, replace `your_token_here` with your Telegram bot token and save
5. Make sure Ollama is running, then:
   ```
   python bot.py
   ```

---

## Quick Start (Manual)

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/restaurant-iq-bot.git
cd restaurant-iq-bot

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env and set TELEGRAM_BOT_TOKEN

# 4. Run
python bot.py
```

---

## Environment Variables

Copy `.env.example` to `.env`:

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | **Required.** Token from @BotFather |
| `OLLAMA_MODEL` | `qwen3-vl:30b` | Vision + report model |
| `OLLAMA_TEXT_MODEL` | `gemma3:4b` | Fast text analysis model |
| `WHISPER_MODEL_SIZE` | `base` | `tiny` / `base` / `small` / `medium` |
| `DB_PATH` | `restaurant_iq.db` | SQLite database file path |

---

## Bot Commands

| Command | Who uses it | What it does |
|---|---|---|
| `/start` | Anyone | Shows welcome message and usage guide |
| `/register Name` | Owner | Registers this Telegram group as a restaurant |
| `/status` | Owner / manager | Shows entry count and breakdown for the current week |
| `/weeklyreport` | Owner | Generates and sends the weekly briefing + PDF |

---

## Telegram Group Setup

1. Create a Telegram group for your restaurant team
2. Add the bot to the group
3. Promote the bot to **admin** (so it can read all messages)
4. Send `/register Your Restaurant Name`
5. Tell staff to send voice notes, photos, or texts — the bot captures everything automatically

Multiple restaurants are supported: each Telegram group is a separate restaurant.

---

## File Layout

```
restaurant-iq-bot/
├── bot.py                  Main entry point
├── config.py               Environment variable loading
├── database.py             SQLite database layer
├── transcriber.py          Whisper voice transcription
├── analyzer.py             Ollama AI analysis
├── report_generator.py     ReportLab PDF generation
├── requirements.txt        Python dependencies
├── .env.example            Environment variable template
├── install.py              Windows one-click installer
├── setup_windows.bat       Windows dependency installer
└── reports/                Generated PDFs (auto-created)
```

---

## Dependencies

```
python-telegram-bot==22.6   Telegram Bot API async client
faster-whisper==1.2.1       Local Whisper transcription
ollama==0.6.1               Ollama Python client
Pillow==12.1.1              Image handling
reportlab==4.4.10           PDF generation
python-dotenv==1.2.2        .env file loading
```

---

## Troubleshooting

**Bot starts but doesn't respond to messages**
- Check the bot is an admin in the group
- Make sure you sent `/register` first

**"Error connecting to Ollama"**
- Open Ollama from the system tray (Windows) or run `ollama serve` in a terminal
- Confirm models are downloaded: `ollama list`

**Voice notes not transcribing**
- Whisper downloads its model on first use (~150 MB for `base`) — wait for it to finish
- Try `WHISPER_MODEL_SIZE=small` in `.env` for better accuracy

**Weekly report is very slow**
- The `qwen3-vl:30b` model takes 3–5 minutes on a typical laptop
- For faster (lower quality) reports, set `OLLAMA_MODEL=gemma3:4b` in `.env`

---

## Outstanding Work

See [DEVELOPER.md](DEVELOPER.md) for the full technical handover including outstanding features, architecture decisions, and implementation notes for the next developer.
