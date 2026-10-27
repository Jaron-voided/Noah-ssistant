from telegram import Update
from telegram.ext import ContextTypes
import asyncio
import re

from db.store import search
import dates
from handlers import date_clarification as clarification
from handlers.google.auth import AuthorizationRequired
from private_paths import PrivatePathError

_CAL_KEYWORDS = (
    "calendar", "schedule", "today", "tomorrow", "this week",
    "event", "meeting", "appointment", "agenda",
)

_ICONS = {"note": "📝", "link": "🔗", "event": "📅", "task": "✅", "image": "🖼️"}
_SEARCH = re.compile(r"\s*(?:find|search(?:\s+for)?|look\s+for)(?:\s+(.*))?\s*", re.I)


def is_capture_search(text: str) -> bool:
    return _SEARCH.fullmatch(text) is not None


def search_keywords(text: str) -> str | None:
    match = _SEARCH.fullmatch(text)
    if not match:
        return None
    keywords = (match[1] or "").strip().rstrip("?").strip()
    if len(keywords) >= 2 and keywords[0] == keywords[-1] and keywords[0] in ("'", '"'):
        keywords = keywords[1:-1].strip()
    return keywords or None


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, *, now=None) -> None:
    lower = text.lower()

    if not is_capture_search(text) and not dates.local_search_question(text) and (any(k in lower for k in _CAL_KEYWORDS) or dates.has_date_language(text)):
        await _calendar_query(update, context, text, now=now)
        return

    keywords = search_keywords(text)
    if keywords is None:
        await update.message.reply_text(
            "Search saved captures with Find <keywords>, Search for <keywords>, or Look for <keywords>. "
            "Search matches raw text and titles; date filters and semantic search are not supported yet."
        )
        return
    hits = search(keywords, limit=5)
    if not hits:
        await update.message.reply_text("Nothing found for that query.")
        return

    lines = ["Here's what I found:\n"]
    for h in hits:
        icon = _ICONS.get(h["type"], "💾")
        label = h["title"] or h["raw"][:60]
        lines.append(f"{icon} {label}")
    await update.message.reply_text("\n".join(lines))


async def _calendar_query(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, *, now=None, answer=""
) -> None:
    from handlers.google import calendar as cal

    reference = dates.local_reference(now)
    try:
        span = dates.resolve_query(text, reference, answer=answer)
    except dates.ClarificationNeeded as exc:
        await clarification.ask(update, context, kind="query", text=text,
                                now=reference, question=str(exc), answer=answer)
        return

    clarification.take(context)
    try:
        start, end = span.bounds()
        raw_events = await asyncio.to_thread(cal.events_for_range, start, end)
        if span.at is not None:
            raw_events = [event for event in raw_events if cal.occurs_at(event, span.at)]
        if re.search(r"\ball[ -]day\b", text, re.I):
            raw_events = [event for event in raw_events if "date" in event.get("start", {})]
        events = [cal.format_event(event) for event in raw_events]
        header = f"📅 Calendar: {dates.describe_span(span)}"
        body = "\n".join(events) if events else "Nothing scheduled."
        await update.message.reply_text(f"{header}\n{body}")

    except (AuthorizationRequired, PrivatePathError) as exc:
        await update.message.reply_text(str(exc))
    except FileNotFoundError:
        await update.message.reply_text("Google Calendar isn't set up. Existing authorization settings were preserved.")
    except Exception:
        await update.message.reply_text("Could not read Google Calendar. Please check its setup and try again.")
