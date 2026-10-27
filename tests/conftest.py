import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

# Override inherited configuration and disable .env before importing application
# modules. Ordinary pytest must not read private local config or use live settings.
# Tests needing other values override config attributes with monkeypatch.
_run_dir = Path(tempfile.gettempdir()) / ("noah-fictional-tests-" + str(uuid.uuid4()))
_environment = patch.dict(os.environ, {
    "TELEGRAM_BOT_TOKEN": "123456:dummy-test-token", "TELEGRAM_USER_ID": "12345",
    "GOOGLE_CREDENTIALS_FILE": str(_run_dir / "no-credentials.json"),
    "GOOGLE_TOKEN_FILE": str(_run_dir / "no-calendar-token.json"),
    "GOOGLE_TASKS_TOKEN_FILE": str(_run_dir / "no-tasks-token.json"),
    "GOOGLE_DRIVE_TOKEN_FILE": str(_run_dir / "no-drive-token.json"),
    "TIMEZONE": "America/New_York", "DB_PATH": str(_run_dir / "fictional.db"),
    "OLLAMA_URL": "http://localhost:11434", "OLLAMA_MODEL": "qwen3:4b",
})
_dotenv = patch("dotenv.load_dotenv", return_value=False)
_environment.start()
_dotenv.start()


def pytest_unconfigure(config):
    _dotenv.stop()
    _environment.stop()
