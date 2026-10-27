from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from db.store import Capture, init_db, recent, save
from handlers.capture import handle_message
from handlers import query
from llm.classifier import Classified


@pytest.fixture(autouse=True)
def captures(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "fictional.db")
    init_db()
    save(Capture(type="note", raw="Fictional orchid notes", title="Fictional orchid notes"))
    save(Capture(type="link", raw="https://example.com/other", title="Unrelated fictional link"))


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "Find fictional orchid notes", "Search for fictional orchid notes",
    "Look for fictional orchid notes", 'Find "fictional orchid notes"',
])
async def test_natural_search_finds_real_capture_without_model_or_calendar(text):
    update, context = MagicMock(), MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    context.user_data = {}
    context.application.bot_data = {}
    with patch("handlers.capture.classify", return_value=Classified(type="query")) as model, \
         patch("handlers.google.calendar.events_for_range") as calendar:
        await handle_message(update, context)
    response = update.message.reply_text.call_args.args[0]
    assert "Fictional orchid notes" in response
    assert "Unrelated fictional link" not in response
    assert len(recent()) == 2
    model.assert_not_called()
    calendar.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["Find", "Search for", "What links did I save yesterday?"])
async def test_missing_keywords_or_unsupported_question_shows_search_help(text):
    update, context = MagicMock(), MagicMock()
    update.message.reply_text = AsyncMock()
    with patch("handlers.query.search", return_value=[]) as search, \
         patch("handlers.google.calendar.events_for_range") as calendar:
        await query.handle(update, context, text)
    assert "Find <keywords>" in update.message.reply_text.call_args.args[0]
    search.assert_not_called()
    calendar.assert_not_called()


@pytest.mark.asyncio
async def test_search_terms_remain_parameterized_data():
    update, context = MagicMock(), MagicMock()
    update.message.reply_text = AsyncMock()
    await query.handle(update, context, "Find ' OR 1=1 --")
    assert update.message.reply_text.call_args.args[0] == "Nothing found for that query."
    assert len(recent()) == 2
