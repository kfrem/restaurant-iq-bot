import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_token_here":
    raise ValueError(
        "TELEGRAM_BOT_TOKEN is not set. "
        "For local development: add it to your .env file. "
        "For Railway/cloud: add it as an environment variable in your project settings."
    )

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError(
        "GEMINI_API_KEY is not set. "
        "Get a key from https://aistudio.google.com/app/apikey and add it to your environment variables."
    )

# Model used for text analysis and invoice photo reading (fast, multimodal)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

# Model used for weekly report generation (higher quality, larger context)
GEMINI_REPORT_MODEL = os.getenv("GEMINI_REPORT_MODEL", "gemini-1.5-pro")

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
DB_PATH = os.getenv("DB_PATH", "restaurant_iq.db")
