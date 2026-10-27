"""Tests for the Calendar write flow: confirmation gate, create_event, skip path."""
import asyncio
import threading
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram import CallbackQuery, InlineKeyboardMarkup, Message, Update, User
from telegram.ext import ContextTypes

import config
from db.store import init_db
from llm.classifier import Classified


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    init_db()


# ── Helpers ────────────────────────────────────────────────────────────────

def make_message_update(text: str) -> tuple:
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


def make_callback_update(callback_data: str, message_text: str = "") -> tuple:
    user = MagicMock(spec=User)
    user.id = 12345
    query = MagicMock(spec=CallbackQuery)
    query.data = callback_data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message = MagicMock(spec=Message)
    query.message.text = message_text
    update = MagicMock(spec=Update)
    update.effective_user = user
    update.callback_query = query
    context = MagicMock()
    context.application.bot_data = {}
    return update, context


# ── Event capture shows confirmation prompt ─────────────────────────────────

@pytest.mark.asyncio
async def test_event_capture_shows_inline_keyboard():
    from handlers.capture import handle_message

    update, context = make_message_update("Dentist April 3rd 2026 at 10am")
    with patch("handlers.capture.classify") as mock_classify:
        mock_classify.return_value = Classified(
            type="event", title="Dentist", event_dt="2026-04-03T10:00:00"
        )
        await handle_message(update, context)

    kwargs = update.message.reply_text.call_args.kwargs
    assert isinstance(kwargs.get("reply_markup"), InlineKeyboardMarkup)
    buttons = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert any(b.startswith("cal_add:") for b in buttons)
    assert any(b.startswith("cal_skip:") for b in buttons)


@pytest.mark.asyncio
async def test_event_capture_stores_pending_in_bot_data():
    from handlers.capture import handle_message

    update, context = make_message_update("Dentist April 3rd 2026 at 10am")
    with patch("handlers.capture.classify") as mock_classify:
        mock_classify.return_value = Classified(
            type="event", title="Dentist", event_dt="2026-04-03T10:00:00"
        )
        await handle_message(update, context)

    # Exactly one pending key should be stored
    pending_keys = [k for k in context.application.bot_data if k.startswith("pending_cal_")]
    assert len(pending_keys) == 1
    pending = context.application.bot_data[pending_keys[0]]
    assert pending["title"] == "Dentist"
    assert pending["event_dt"] == "2026-04-03T10:00:00-04:00"


# ── Calendar NOT called before confirmation ──────────────────────────────────

@pytest.mark.asyncio
async def test_calendar_not_called_before_confirmation():
    from handlers.capture import handle_message

    update, context = make_message_update("Dentist April 3rd 2026 at 10am")
    with patch("handlers.capture.classify") as mock_classify, \
         patch("handlers.google.calendar.create_event") as mock_create:
        mock_classify.return_value = Classified(
            type="event", title="Dentist", event_dt="2026-04-03T10:00:00"
        )
        await handle_message(update, context)

    mock_create.assert_not_called()


# ── Confirming "Add" calls create_event with correct args ────────────────────

@pytest.mark.asyncio
async def test_add_confirmation_calls_create_event():
    from handlers.calendar_confirm import handle_callback

    update, context = make_callback_update("cal_add:1", "📅 Saved as event\nDentist")
    context.application.bot_data["pending_cal_1"] = {
        "title": "Dentist",
        "event_dt": "2026-04-03T10:00:00",
        "description": None,
    }

    with patch("handlers.calendar_confirm.cal.create_event") as mock_create:
        mock_create.return_value = {"htmlLink": "https://calendar.google.com/event?eid=abc"}
        await handle_callback(update, context)

    mock_create.assert_called_once_with(
        summary="Dentist",
        start_dt="2026-04-03T10:00:00",
        description=None,
    )
    reply = update.callback_query.edit_message_text.call_args[0][0]
    assert "✅" in reply
    assert "Dentist" in reply
    assert "calendar.google.com" in reply


@pytest.mark.asyncio
async def test_add_confirmation_clears_pending_data():
    from handlers.calendar_confirm import handle_callback

    update, context = make_callback_update("cal_add:1")
    context.application.bot_data["pending_cal_1"] = {
        "title": "Dentist",
        "event_dt": "2026-04-03T10:00:00",
        "description": None,
    }

    with patch("handlers.calendar_confirm.cal.create_event") as mock_create:
        mock_create.return_value = {}
        await handle_callback(update, context)

    assert "pending_cal_1" not in context.application.bot_data


# ── Skip does NOT call create_event ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_skip_does_not_call_create_event():
    from handlers.calendar_confirm import handle_callback

    update, context = make_callback_update("cal_skip:1", "📅 Saved as event")
    context.application.bot_data["pending_cal_1"] = {
        "title": "Dentist",
        "event_dt": "2026-04-03T10:00:00",
        "description": None,
    }

    with patch("handlers.calendar_confirm.cal.create_event") as mock_create:
        await handle_callback(update, context)

    mock_create.assert_not_called()
    reply = update.callback_query.edit_message_text.call_args[0][0]
    assert "Not added" in reply
    assert "pending_cal_1" not in context.application.bot_data


# ── Stale callback (bot restarted, bot_data gone) ────────────────────────────

@pytest.mark.asyncio
async def test_stale_callback_shows_expiry_message():
    from handlers.calendar_confirm import handle_callback

    update, context = make_callback_update("cal_add:99")
    # bot_data is empty — simulates bot restart

    with patch("handlers.calendar_confirm.cal.create_event") as mock_create:
        await handle_callback(update, context)

    mock_create.assert_not_called()
    reply = update.callback_query.answer.call_args[0][0]
    assert "expired" in reply.lower()
    update.callback_query.edit_message_text.assert_not_awaited()


# ── create_event builds the correct Google API payload ───────────────────────

def test_create_event_timed_defaults_to_one_hour():
    from handlers.google.calendar import create_event

    with patch("handlers.google.calendar._service") as mock_svc:
        mock_svc.return_value.events.return_value.insert.return_value.execute.return_value = {}
        create_event(summary="Standup", start_dt="2026-04-03T09:00:00")

    body = mock_svc.return_value.events.return_value.insert.call_args.kwargs["body"]
    assert body["summary"] == "Standup"
    assert "dateTime" in body["start"]
    assert "dateTime" in body["end"]
    start = datetime.fromisoformat(body["start"]["dateTime"])
    end = datetime.fromisoformat(body["end"]["dateTime"])
    assert int((end - start).total_seconds()) == 3600


@pytest.mark.parametrize("start_day, exclusive_end", [
    ("2026-04-03", "2026-04-04"),
    ("2026-12-31", "2027-01-01"),
    ("2028-02-28", "2028-02-29"),
    ("2028-02-29", "2028-03-01"),
])
def test_create_event_all_day(start_day, exclusive_end):
    from handlers.google.calendar import create_event

    with patch("handlers.google.calendar._service") as mock_svc:
        mock_svc.return_value.events.return_value.insert.return_value.execute.return_value = {}
        create_event(summary="Fictional conference day", start_dt=start_day)

    body = mock_svc.return_value.events.return_value.insert.call_args.kwargs["body"]
    assert body["summary"] == "Fictional conference day"
    assert body["start"] == {"date": start_day}
    assert body["end"] == {"date": exclusive_end}
    assert (date.fromisoformat(exclusive_end) - date.fromisoformat(start_day)).days == 1


def test_create_event_all_day_preserves_explicit_exclusive_end():
    from handlers.google.calendar import create_event

    with patch("handlers.google.calendar._service") as mock_svc:
        create_event(summary="Fictional conference", start_dt="2026-11-12", end_dt="2026-11-15")

    body = mock_svc.return_value.events.return_value.insert.call_args.kwargs["body"]
    assert body["end"] == {"date": "2026-11-15"}


@pytest.mark.parametrize("end_day", ["2026-11-12", "2026-11-11", "2026-11-13T10:00:00"])
def test_create_event_rejects_invalid_all_day_end_before_api_call(end_day):
    from handlers.google.calendar import create_event

    with patch("handlers.google.calendar._service") as mock_svc:
        with pytest.raises(ValueError):
            create_event(summary="Fictional event", start_dt="2026-11-12", end_dt=end_day)
    mock_svc.assert_not_called()


@pytest.mark.asyncio
async def test_double_add_does_not_repeat_insert_or_overwrite_success():
    from handlers.calendar_confirm import handle_callback

    update, context = make_callback_update("cal_add:1")
    context.application.bot_data["pending_cal_1"] = {
        "title": "Fictional meeting", "event_dt": "2026-11-12T15:00:00"
    }
    with patch("handlers.calendar_confirm.cal.create_event", return_value={}) as create:
        await handle_callback(update, context)
        await handle_callback(update, context)

    create.assert_called_once()
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "already" in update.callback_query.answer.call_args.args[0].lower()


@pytest.mark.asyncio
async def test_overlapping_add_callbacks_consume_pending_before_reply():
    from handlers.calendar_confirm import handle_callback

    first, context = make_callback_update("cal_add:1")
    second, _ = make_callback_update("cal_add:1")
    context.application.bot_data["pending_cal_1"] = {
        "title": "Fictional meeting", "event_dt": "2026-11-12T15:00:00"
    }
    editing, release = asyncio.Event(), asyncio.Event()

    async def hold_reply(*args, **kwargs):
        editing.set()
        await release.wait()

    first.callback_query.edit_message_text.side_effect = hold_reply
    with patch("handlers.calendar_confirm.cal.create_event", return_value={}) as create:
        task = asyncio.create_task(handle_callback(first, context))
        try:
            await asyncio.wait_for(editing.wait(), 2)
            await handle_callback(second, context)
        finally:
            release.set()
            await task
    create.assert_called_once()
    second.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_insert_is_not_retried_or_exposed_on_second_tap(caplog):
    from handlers.calendar_confirm import handle_callback

    update, context = make_callback_update("cal_add:1")
    context.application.bot_data["pending_cal_1"] = {
        "title": "Fictional meeting", "event_dt": "2026-11-12T15:00:00"
    }
    with patch("handlers.calendar_confirm.cal.create_event",
               side_effect=RuntimeError("PRIVATE_GOOGLE_RESPONSE")) as create:
        await handle_callback(update, context)
        await handle_callback(update, context)
    create.assert_called_once()
    assert "pending_cal_1" not in context.application.bot_data
    assert "PRIVATE_GOOGLE_RESPONSE" not in str(update.callback_query.edit_message_text.call_args_list)
    assert "PRIVATE_GOOGLE_RESPONSE" not in caplog.text


@pytest.mark.asyncio
async def test_successful_insert_with_failed_reply_stays_consumed(caplog):
    from handlers.calendar_confirm import handle_callback
    from telegram.error import TelegramError

    update, context = make_callback_update("cal_add:1")
    context.application.bot_data["pending_cal_1"] = {
        "title": "Fictional meeting", "event_dt": "2026-11-12T15:00:00"
    }
    update.callback_query.edit_message_text.side_effect = TelegramError("PRIVATE_REPLY_DETAIL")
    with patch("handlers.calendar_confirm.cal.create_event", return_value={}) as create:
        await handle_callback(update, context)
        await handle_callback(update, context)
    create.assert_called_once()
    assert "pending_cal_1" not in context.application.bot_data
    assert "PRIVATE_REPLY_DETAIL" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("first_action, second_action", [
    ("skip", "skip"), ("add", "skip"), ("skip", "add"),
])
async def test_conflicting_or_repeated_buttons_do_not_change_first_decision(first_action, second_action):
    from handlers.calendar_confirm import handle_callback

    update, context = make_callback_update(f"cal_{first_action}:1", "Fictional event")
    context.application.bot_data["pending_cal_1"] = {
        "title": "Fictional meeting", "event_dt": "2026-11-12T15:00:00"
    }
    with patch("handlers.calendar_confirm.cal.create_event", return_value={}) as create:
        await handle_callback(update, context)
        update.callback_query.data = f"cal_{second_action}:1"
        await handle_callback(update, context)
    assert create.call_count == (1 if first_action == "add" else 0)
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [None, "cal_add:bad-id", "cal_add:-1", "other:1"])
async def test_malformed_calendar_callback_does_not_write(data):
    from handlers.calendar_confirm import handle_callback

    update, context = make_callback_update(data)
    context.application.bot_data["pending_cal_1"] = {
        "title": "Fictional event", "event_dt": "2026-11-12"
    }
    with patch("handlers.calendar_confirm.cal.create_event") as create:
        await handle_callback(update, context)
    create.assert_not_called()
    assert "pending_cal_1" in context.application.bot_data
    update.callback_query.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_title_is_rendered_as_plain_text():
    from handlers.calendar_confirm import handle_callback

    update, context = make_callback_update("cal_add:1")
    context.application.bot_data["pending_cal_1"] = {
        "title": "Fictional [planning]*_session", "event_dt": "2026-11-12T15:00:00"
    }
    with patch("handlers.calendar_confirm.cal.create_event", return_value={}):
        await handle_callback(update, context)
    args, kwargs = update.callback_query.edit_message_text.call_args
    assert "Fictional [planning]*_session" in args[0]
    assert kwargs.get("parse_mode") is None


@pytest.mark.asyncio
async def test_slow_insert_keeps_event_loop_responsive_and_blocks_second_tap():
    from handlers.calendar_confirm import handle_callback

    update, context = make_callback_update("cal_add:1")
    duplicate, _ = make_callback_update("cal_add:1")
    context.application.bot_data["pending_cal_1"] = {
        "title": "Fictional meeting", "event_dt": "2027-01-15T17:00:00-05:00"
    }
    started, release = threading.Event(), threading.Event()

    def slow_insert(**kwargs):
        started.set()
        if not release.wait(3):
            raise RuntimeError("Insertion blocked the event loop")
        return {}

    with patch("handlers.calendar_confirm.cal.create_event", side_effect=slow_insert) as create:
        task = asyncio.create_task(handle_callback(update, context))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), 2)
            assert not task.done()
            await handle_callback(duplicate, context)
            create.assert_called_once()
        finally:
            release.set()
            await task
    assert "pending_cal_1" not in context.application.bot_data


@pytest.mark.asyncio
async def test_cancelled_insert_does_not_restore_or_retry_pending_addition():
    from handlers.calendar_confirm import handle_callback

    update, context = make_callback_update("cal_add:1")
    context.application.bot_data["pending_cal_1"] = {
        "title": "Fictional meeting", "event_dt": "2027-01-15T17:00:00-05:00"
    }
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def insert(**kwargs):
        started.set()
        release.wait(3)
        finished.set()
        return {}

    with patch("handlers.calendar_confirm.cal.create_event", side_effect=insert) as create:
        task = asyncio.create_task(handle_callback(update, context))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 1), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await handle_callback(update, context)
            create.assert_called_once()
        finally:
            release.set()
            await asyncio.to_thread(finished.wait, 2)
            if not task.done():
                await task
    assert "pending_cal_1" not in context.application.bot_data


def test_create_event_includes_description():
    from handlers.google.calendar import create_event

    with patch("handlers.google.calendar._service") as mock_svc:
        mock_svc.return_value.events.return_value.insert.return_value.execute.return_value = {}
        create_event(summary="Meeting", start_dt="2026-04-03T14:00:00", description="Bring laptop")

    body = mock_svc.return_value.events.return_value.insert.call_args.kwargs["body"]
    assert body["description"] == "Bring laptop"


def test_create_event_uses_primary_calendar():
    from handlers.google.calendar import create_event

    with patch("handlers.google.calendar._service") as mock_svc:
        mock_svc.return_value.events.return_value.insert.return_value.execute.return_value = {}
        create_event(summary="Test", start_dt="2026-04-03T10:00:00")

    insert_kwargs = mock_svc.return_value.events.return_value.insert.call_args.kwargs
    assert insert_kwargs["calendarId"] == "primary"
