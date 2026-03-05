import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_token_here":
    raise ValueError(
        "TELEGRAM_BOT_TOKEN is not set.\n"
        "  - Local dev: copy .env.example to .env and add your token\n"
        "  - Railway/cloud: add TELEGRAM_BOT_TOKEN in the Variables tab of your service"
    )

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
    raise ValueError(
        "GEMINI_API_KEY is not set.\n"
        "  - Get a free key at https://aistudio.google.com/app/apikey\n"
        "  - Local dev: add it to your .env file\n"
        "  - Railway/cloud: add GEMINI_API_KEY in the Variables tab of your service"
    )

# Gemini model — gemini-1.5-flash is free tier, fast, and supports vision
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
DB_PATH = os.getenv("DB_PATH", "restaurant_iq.db")
