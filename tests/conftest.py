import os

# Set dummy values before any module that reads config.py is imported.
# Tests that need specific values override via monkeypatch.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "1234567890:AAtest_token_for_pytest_only")
os.environ.setdefault("TELEGRAM_USER_ID", "12345")
os.environ.setdefault("GOOGLE_CREDENTIALS_FILE", "credentials.json")
os.environ.setdefault("GOOGLE_TOKEN_FILE", "token.json")
os.environ.setdefault("TIMEZONE", "America/New_York")
os.environ.setdefault("DB_PATH", "noah_test.db")
os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")
os.environ.setdefault("OLLAMA_MODEL", "qwen3:4b")
