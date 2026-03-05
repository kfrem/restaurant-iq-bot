import os
from dotenv import load_dotenv

load_dotenv()

# ── Required ─────────────────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_token_here":
    raise ValueError(
        "TELEGRAM_BOT_TOKEN is not set.\n"
        "  → Local dev: copy .env.example to .env and add your bot token\n"
        "  → Railway: add TELEGRAM_BOT_TOKEN in the Variables tab"
    )

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
    raise ValueError(
        "GEMINI_API_KEY is not set. This is required from day one.\n"
        "  → Get a FREE key at: https://aistudio.google.com/app/apikey\n"
        "  → Railway: add GEMINI_API_KEY in the Variables tab"
    )

# ── Optional — add these in Railway before you hit the thresholds ─────────────
# 50+ restaurants: Groq (free). Get key at https://console.groq.com/keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# 100+ restaurants: Anthropic / Claude (paid). Get key at https://console.anthropic.com/
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# ── Model names (safe to leave as defaults) ───────────────────────────────────
GEMINI_MODEL     = os.getenv("GEMINI_MODEL",     "gemini-2.0-flash")

# ── Other settings ────────────────────────────────────────────────────────────
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
DB_PATH            = os.getenv("DB_PATH",            "restaurant_iq.db")
