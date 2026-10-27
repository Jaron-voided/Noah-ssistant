from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
import main
from handlers.calendar_confirm import handle_callback


def make_update(user_id):
    update = MagicMock()
    update.effective_user = None if user_id is None else MagicMock(id=user_id)
    update.message.text = "PRIVATE_FICTIONAL_MESSAGE"
    update.message.reply_text = AsyncMock()
    update.callback_query.data = "cal_add:1"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}
    context.application.bot_data = {"pending_cal_1": {
        "title": "Fictional event", "event_dt": "2026-11-12T15:00:00"
    }}
    return update, context


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [None, 99999])
@pytest.mark.parametrize("handler_name", ["on_message", "cmd_start", "cmd_today", "cmd_week"])
async def test_unauthorized_messages_never_reach_services(handler_name, user_id, caplog):
    update, context = make_update(user_id)
    with patch("main.capture_handler.handle_message", new_callable=AsyncMock) as capture, \
         patch("handlers.google.calendar.events_for_range") as calendar:
        await getattr(main, handler_name)(update, context)
    capture.assert_not_awaited()
    calendar.assert_not_called()
    update.message.reply_text.assert_not_awaited()
    assert "PRIVATE_FICTIONAL_MESSAGE" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [None, 99999])
@pytest.mark.parametrize("action", ["add", "skip"])
async def test_unauthorized_callbacks_cannot_consume_or_create(user_id, action):
    update, context = make_update(user_id)
    update.callback_query.data = f"cal_{action}:1"
    with patch("handlers.calendar_confirm.cal.create_event") as create:
        await handle_callback(update, context)
    create.assert_not_called()
    update.callback_query.answer.assert_not_awaited()
    update.callback_query.edit_message_text.assert_not_awaited()
    assert "pending_cal_1" in context.application.bot_data


@pytest.mark.asyncio
async def test_authorized_message_reaches_capture():
    update, context = make_update(config.TELEGRAM_USER_ID)
    with patch("main.capture_handler.handle_message", new_callable=AsyncMock) as capture:
        await main.on_message(update, context)
    capture.assert_awaited_once_with(update, context)


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_name", ["cmd_start", "cmd_today", "cmd_week"])
async def test_authorized_commands_reply(handler_name):
    update, context = make_update(config.TELEGRAM_USER_ID)
    with patch("handlers.google.calendar.events_for_range", return_value=[]):
        await getattr(main, handler_name)(update, context)
    update.message.reply_text.assert_awaited_once()
