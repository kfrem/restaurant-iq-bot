import os
from dotenv import load_dotenv

load_dotenv()

# ── Required ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_token_here":
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env — add your token from @BotFather")

# ── AI Backend — Claude API (recommended) or Ollama (self-hosted fallback) ───
# If ANTHROPIC_API_KEY is set, Claude API is used automatically.
# Claude Haiku costs ~$0.002/restaurant/month — no GPU server needed.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", None)

# Ollama fallback settings (used only when ANTHROPIC_API_KEY is not set)
OLLAMA_MODEL      = os.getenv("OLLAMA_MODEL", "qwen3-vl:30b")
OLLAMA_TEXT_MODEL = os.getenv("OLLAMA_TEXT_MODEL", "gemma3:4b")
OLLAMA_HOST       = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# ── Voice transcription ───────────────────────────────────────────────────────
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
WHISPER_LANGUAGE   = os.getenv("WHISPER_LANGUAGE", None)  # None = auto-detect

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "restaurant_iq.db")

# ── SaaS / Billing ───────────────────────────────────────────────────────────
# Stripe API keys — needed to process subscription payments
STRIPE_SECRET_KEY      = os.getenv("STRIPE_SECRET_KEY", None)
STRIPE_WEBHOOK_SECRET  = os.getenv("STRIPE_WEBHOOK_SECRET", None)

# Public upgrade URL shown to users when trial expires
UPGRADE_URL = os.getenv("UPGRADE_URL", "https://restaurantiq.app/upgrade")

# ── Scheduling ────────────────────────────────────────────────────────────────
REPORT_DAY  = os.getenv("REPORT_DAY", "monday").lower()
REPORT_TIME = os.getenv("REPORT_TIME", "08:00")

# Daily flash report time (sent to all active restaurants each evening)
FLASH_REPORT_TIME = os.getenv("FLASH_REPORT_TIME", "18:00")

# ── Admin ─────────────────────────────────────────────────────────────────────
# Telegram user ID of the platform admin — receives health alerts
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID", None)

# ── Flivio integration ────────────────────────────────────────────────────────
# URL of your Flivio instance (e.g. https://flivio.yourdomain.com)
FLIVIO_API_URL = os.getenv("FLIVIO_API_URL", None)
# API key for bot→Flivio data push (set in Flivio admin panel)
FLIVIO_API_KEY = os.getenv("FLIVIO_API_KEY", None)
# Public URL shown to Managed/Enterprise clients for their dashboard
FLIVIO_DASHBOARD_URL = os.getenv("FLIVIO_DASHBOARD_URL", "https://app.flivio.com")

# ── Analyst team ──────────────────────────────────────────────────────────────
# Comma-separated Telegram user IDs of your analyst team
# These users can use /analyst commands in any chat with the bot
ANALYST_TELEGRAM_IDS = [
    x.strip() for x in os.getenv("ANALYST_TELEGRAM_IDS", "").split(",") if x.strip()
]
# How long (hours) an analyst has to review a report before it auto-sends
ANALYST_REVIEW_WINDOW_HOURS = int(os.getenv("ANALYST_REVIEW_WINDOW_HOURS", "4"))

# ── Default UK region ─────────────────────────────────────────────────────────
# Used for supplier database searches when client hasn't specified their region
DEFAULT_REGION = os.getenv("DEFAULT_REGION", "london")
