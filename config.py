import os
from dotenv import load_dotenv

load_dotenv()

# ── Required ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_token_here":
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env — add your token from @BotFather")

# ── AI Backend — multi-backend with automatic fallback ────────────────────────
#
# Priority order (cheapest first):
#   1. Groq         — free tier (30 RPM, llama-3.3-70b) — text only, very fast
#   2. Google Gemini— free tier (15 RPM, Flash)          — text + vision
#   3. Ollama       — local / self-hosted                 — text + vision
#   4. Anthropic    — paid (Enterprise tier only)         — text + vision
#
# Subscription-tier model routing:
#   Solo / Trial  → Groq (text) + Gemini Flash (vision/reports)  ← FREE
#   Managed       → Gemini 1.5 Pro reports + Gemini Flash analysis
#   Enterprise    → Claude Sonnet reports + Claude Haiku analysis
#
# Set any combination of keys below — unused backends are silently skipped.

# ── Groq (free tier: console.groq.com/keys — no credit card) ─────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# ── Google Gemini (free tier: aistudio.google.com — no credit card) ──────────
GOOGLE_API_KEY      = os.getenv("GOOGLE_API_KEY", "")
GEMINI_FAST_MODEL   = os.getenv("GEMINI_FAST_MODEL", "gemini-1.5-flash")   # free
GEMINI_SMART_MODEL  = os.getenv("GEMINI_SMART_MODEL", "gemini-1.5-pro")    # cheap paid

# ── Anthropic Claude (Enterprise tier — console.anthropic.com) ───────────────
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_FAST_MODEL  = os.getenv("CLAUDE_FAST_MODEL",  "claude-haiku-4-5-20251001")
CLAUDE_SMART_MODEL = os.getenv("CLAUDE_SMART_MODEL", "claude-sonnet-4-6")

# ── Ollama (local / self-hosted fallback) ─────────────────────────────────────
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

# Stripe Price IDs — one per plan (create these in your Stripe dashboard)
# Stripe Dashboard → Products → Add product → Add price → copy the price_XXXX ID
STRIPE_SOLO_PRICE_ID       = os.getenv("STRIPE_SOLO_PRICE_ID", None)        # £149/month
STRIPE_MANAGED_PRICE_ID    = os.getenv("STRIPE_MANAGED_PRICE_ID", None)     # £499/month
STRIPE_ENTERPRISE_PRICE_ID = os.getenv("STRIPE_ENTERPRISE_PRICE_ID", None)  # £999/month

# Port for the Stripe webhook HTTP server (must be reachable from the internet)
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "8080"))

# Public upgrade URL shown to users when trial expires (fallback if Stripe not set up)
UPGRADE_URL = os.getenv("UPGRADE_URL", "https://restaurantiq.app/upgrade")

# ── Scheduling ────────────────────────────────────────────────────────────────
REPORT_DAY  = os.getenv("REPORT_DAY", "monday").lower()
REPORT_TIME = os.getenv("REPORT_TIME", "08:00")

# Daily flash report time (sent to all active restaurants each evening)
FLASH_REPORT_TIME = os.getenv("FLASH_REPORT_TIME", "18:00")

# ── Dashboard ─────────────────────────────────────────────────────────────────
# Optional password for the web dashboard at http://YOUR-SERVER:WEBHOOK_PORT/
# If set, add ?token=YOUR_TOKEN to the URL to access the dashboard.
# If left blank, the dashboard is open to anyone on the same network (dev mode).
# Example: DASHBOARD_TOKEN=MySecretPassword123
DASHBOARD_TOKEN = os.getenv("DASHBOARD_TOKEN", "")

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
