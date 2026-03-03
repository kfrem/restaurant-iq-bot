import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_token_here":
    raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env — open .env and add your token")

# Vision + text model (qwen3-vl:30b — used for invoice photos and weekly reports)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-vl:30b")

# Fast text-only model (gemma3:4b — used for quick text entry analysis)
OLLAMA_TEXT_MODEL = os.getenv("OLLAMA_TEXT_MODEL", "gemma3:4b")

# Ollama API host (default: local; change for remote Ollama servers)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Whisper voice transcription
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", None)  # None = auto-detect

# Database file path
DB_PATH = os.getenv("DB_PATH", "restaurant_iq.db")

# Optional: Telegram user ID of the admin (receives Ollama health alerts)
ADMIN_TELEGRAM_ID = os.getenv("ADMIN_TELEGRAM_ID", None)

# Scheduled weekly report delivery (server local time)
REPORT_DAY = os.getenv("REPORT_DAY", "monday").lower()
REPORT_TIME = os.getenv("REPORT_TIME", "08:00")
