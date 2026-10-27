import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import Chat, InlineKeyboardMarkup, Message, Update, User
from telegram.ext import ContextTypes

import config
from db.store import init_db
from llm.classifier import Classified, ClassifierError


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    init_db()


def make_update(text: str) -> tuple:
    user = MagicMock(spec=User)
    user.id = 12345
    message = MagicMock(spec=Message)
    message.text = text
    message.reply_text = AsyncMock()
    update = MagicMock(spec=Update)
    update.effective_user = user
    update.message = message
    context = MagicMock()
    context.user_data = {}
    context.application.bot_data = {}
    return update, context


@pytest.mark.asyncio
async def test_capture_note_stores_and_confirms():
    from handlers.capture import handle_message

    update, context = make_update("Remember to call mom")
    with patch("handlers.capture.classify") as mock_classify:
        mock_classify.return_value = Classified(type="note", title="Call mom")
        await handle_message(update, context)

    update.message.reply_text.assert_called_once()
    reply = update.message.reply_text.call_args[0][0]
    assert "note" in reply
    assert "#1" in reply


@pytest.mark.asyncio
async def test_capture_link_stores_url():
    from handlers.capture import handle_message

    update, context = make_update("https://example.com")
    with patch("handlers.capture.classify") as mock_classify:
        mock_classify.return_value = Classified(
            type="link", title="Example", url="https://example.com"
        )
        await handle_message(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "link" in reply
    assert "https://example.com" in reply


@pytest.mark.asyncio
async def test_capture_event_shows_keyboard_and_formatted_time():
    from handlers.capture import handle_message

    update, context = make_update("Dentist April 3rd 2026 at 10am")
    with patch("handlers.capture.classify") as mock_classify:
        mock_classify.return_value = Classified(
            type="event", title="Dentist", event_dt="2026-04-03T10:00:00"
        )
        await handle_message(update, context)

    call_kwargs = update.message.reply_text.call_args.kwargs
    # Must show an inline keyboard with Add / Skip buttons
    assert isinstance(call_kwargs.get("reply_markup"), InlineKeyboardMarkup)
    buttons = [
        b.callback_data
        for row in call_kwargs["reply_markup"].inline_keyboard
        for b in row
    ]
    assert any(b.startswith("cal_add:") for b in buttons)
    assert any(b.startswith("cal_skip:") for b in buttons)
    # Message body shows event title and a human-readable date, not raw ISO
    text = update.message.reply_text.call_args[0][0]
    assert "event" in text
    assert "Dentist" in text
    assert "Apr 3" in text
    assert "2026-04-03" in text  # exact resolved date is visible


@pytest.mark.asyncio
async def test_query_routes_to_query_handler():
    from handlers.capture import handle_message

    update, context = make_update("What's on my calendar?")
    with patch("handlers.capture.classify") as mock_classify, \
         patch("handlers.query.handle", new_callable=AsyncMock) as mock_query:
        mock_classify.return_value = Classified(type="query")
        await handle_message(update, context)

    mock_query.assert_called_once()
    # query routing must NOT call reply_text directly (query handler does that)
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_empty_message_does_nothing():
    from handlers.capture import handle_message

    update, context = make_update("")
    await handle_message(update, context)
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_classifier_error_sends_error_message():
    from handlers.capture import handle_message

    update, context = make_update("Some message")
    with patch("handlers.capture.classify") as mock_classify:
        mock_classify.side_effect = ClassifierError("Ollama is not reachable")
        await handle_message(update, context)

    update.message.reply_text.assert_called_once()
    reply = update.message.reply_text.call_args[0][0]
    assert "⚠️" in reply
    assert "Ollama is not reachable" in reply


@pytest.mark.asyncio
async def test_slow_classifier_does_not_block_telegram_event_loop():
    from handlers.capture import handle_message

    update, context = make_update("Fictional note")
    started, release = threading.Event(), threading.Event()

    def slow_classify(text, **kwargs):
        started.set()
        if not release.wait(timeout=3):
            raise RuntimeError("Classifier blocked the event loop")
        return Classified(type="note", title="Fictional note")

    with patch("handlers.capture.classify", side_effect=slow_classify):
        task = asyncio.create_task(handle_message(update, context))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), 2)
            assert not task.done()
            await asyncio.sleep(0)
        finally:
            release.set()
            await task
    update.message.reply_text.assert_awaited_once()
