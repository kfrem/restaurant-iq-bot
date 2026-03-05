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

# Vision + text model (qwen3-vl:30b — used for invoice photos and weekly reports)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-vl:30b")

# Fast text-only model (gemma3:4b — used for quick text entry analysis)
OLLAMA_TEXT_MODEL = os.getenv("OLLAMA_TEXT_MODEL", "gemma3:4b")

# Ollama server URL — set OLLAMA_HOST to point to a remote Ollama instance on Railway/cloud
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
DB_PATH = os.getenv("DB_PATH", "restaurant_iq.db")
