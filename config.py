import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        sys.exit(f"ERROR: {name} is not set. Add it to .env or your environment.")
    return val

def _optional(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default

TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_USER_ID: int = int(_require("TELEGRAM_USER_ID"))

GOOGLE_CREDENTIALS_FILE: Path = Path(_optional("GOOGLE_CREDENTIALS_FILE", "credentials.json"))
GOOGLE_TOKEN_FILE: Path = Path(_optional("GOOGLE_TOKEN_FILE", "token.json"))

TIMEZONE: str = _optional("TIMEZONE", "America/New_York")
DB_PATH: Path = Path(_optional("DB_PATH", "noah.db"))

OLLAMA_URL: str = _optional("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL: str = _optional("OLLAMA_MODEL", "qwen3:4b")
