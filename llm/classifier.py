from __future__ import annotations

from typing import Literal, Optional
from datetime import datetime

import requests
from pydantic import BaseModel, ValidationError

import config
import dates

CaptureType = Literal["note", "link", "event", "task", "query", "image"]

_SYSTEM = """You are a message classifier for a personal assistant.
Classify the user's message into exactly one type:
  note   — a plain text thought, memo, or idea
  link   — contains a URL to save for later
  event  — mentions a specific date/time for something happening
  task   — something the user needs to do
  query  — a question or retrieval request ("what's on my calendar?", "what did I save?")
  image  — the message is an image with no meaningful text

Extract metadata when present:
  title      — short name for the item
  url        — the URL if type is link
  event_dt   — ISO 8601 date for all-day events (e.g. 2026-04-03), or datetime for timed events
               (e.g. 2026-04-03T10:00:00); assume America/New_York if no tz given
  description — any extra context

Respond with ONLY a JSON object using exactly these keys:
{"type": "<type>", "title": "<string or null>", "url": "<string or null>", "event_dt": "<string or null>", "description": "<string or null>"}
Set fields to null when they do not apply. No extra text outside the JSON."""


class Classified(BaseModel):
    type: CaptureType
    title: Optional[str] = None
    url: Optional[str] = None
    event_dt: Optional[str] = None
    description: Optional[str] = None


class ClassifierError(Exception):
    """Raised when Ollama is unavailable or returns unusable output."""


def classify(text: str, *, now: datetime | None = None) -> Classified:
    reference = dates.local_reference(now)
    clock_context = (
        f"\nCurrent local date and time: {reference.isoformat()} ({config.TIMEZONE}). "
        "Use this reference for relative dates. Never invent a missing date or time. "
        "Questions about the calendar are queries; an event to capture is an event."
    )
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM + clock_context},
            {"role": "user", "content": text},
        ],
        "format": "json",
        "stream": False,
        # Classification needs a short JSON answer, not Qwen's reasoning trace.
        "think": False,
    }
    try:
        resp = requests.post(
            f"{config.OLLAMA_URL}/api/chat",
            json=payload,
            timeout=(5, 120),  # connect / read; allow for a cold local model
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        raise ClassifierError("Ollama timed out — the model may still be loading.") from None
    except requests.exceptions.ConnectionError:
        raise ClassifierError("Ollama is not reachable — is it running?") from None
    except requests.exceptions.RequestException:
        raise ClassifierError("Ollama request failed. Check that the model is available.") from None

    try:
        content = resp.json()["message"]["content"]
        return Classified.model_validate_json(content)
    except (KeyError, TypeError, ValueError, ValidationError):
        raise ClassifierError("Could not parse classifier output. Expected classification JSON.") from None
