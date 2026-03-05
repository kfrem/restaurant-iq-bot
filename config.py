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

# Ollama host — defaults to localhost. On Railway or other cloud deployments,
# set OLLAMA_HOST to the URL of your external Ollama instance
# (e.g. http://your-ollama-service.railway.internal:11434).
# The ollama Python client picks this up automatically.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "")  # read for documentation; ollama client uses it natively

# Vision + text model (qwen3-vl:30b — used for invoice photos and weekly reports)
# Requires ~20 GB RAM. For smaller hosts use qwen2.5-vl:7b or llava:7b.
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-vl:30b")

# Fast text-only model (gemma3:4b — used for quick text entry analysis)
OLLAMA_TEXT_MODEL = os.getenv("OLLAMA_TEXT_MODEL", "gemma3:4b")

WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "base")
DB_PATH = os.getenv("DB_PATH", "restaurant_iq.db")
