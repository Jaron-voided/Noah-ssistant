"""Fictional Tasks data only; no real Google or Telegram requests."""
import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import TelegramError

import config
import main
from db import store
from handlers import tasks
from handlers.google import tasks as api
from handlers.google.tasks_auth import TasksAuthorizationRequired
from llm.classifier import Classified


@pytest.fixture(autouse=True)
def local_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "fictional.db")
    store.init_db()


def message(text="/task Buy fictional index cards", user_id=None):
    update, context = MagicMock(), MagicMock()
    update.effective_user.id = config.TELEGRAM_USER_ID if user_id is None else user_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.callback_query.data = "task_add:1"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    context.user_data = {}
    context.application.bot_data = {}
    return update, context


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/task Buy fictional index cards", "Task: Buy fictional index cards"])
async def test_explicit_capture_saves_and_previews_without_model_or_google(text):
    update, context = message(text)
    with patch("handlers.capture.classify") as classify, patch.object(api, "create_task") as create:
        if text.startswith("/"):
            await tasks.command_add(update, context)
        else:
            await main.on_message(update, context)
    classify.assert_not_called()
    create.assert_not_called()
    assert store.recent()[0]["raw"] == "Buy fictional index cards"
    assert store.recent()[0]["type"] == "task"
    args = update.message.reply_text.call_args
    assert "Buy fictional index cards" in args.args[0]
    assert "Due date/reminder: not set" in args.args[0]
    assert "default Google Tasks list" in args.args[0]
    assert not args.kwargs.get("parse_mode")
    assert args.kwargs["link_preview_options"].is_disabled is True
    buttons = args.kwargs["reply_markup"].inline_keyboard[0]
    assert [b.callback_data for b in buttons] == ["task_add:1", "task_skip:1"]


@pytest.mark.asyncio
async def test_natural_task_classification_gets_preview_and_preserves_original_notes():
    update, context = message("Buy fictional index cards tomorrow")
    with patch("handlers.capture.classify", return_value=Classified(type="task", title="Buy cards")), \
         patch.object(api, "create_task") as create:
        await main.on_message(update, context)
    create.assert_not_called()
    assert context.application.bot_data["pending_task_1"] == {
        "title": "Buy cards", "notes": "Buy fictional index cards tomorrow"}
    assert "Date/time words remain notes only" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [99999, "missing"])
@pytest.mark.parametrize("entry", ["command_add", "command_list", "handle_callback", "on_message"])
async def test_unauthorized_input_is_silent_and_cannot_consume_write_or_read(user, entry):
    update, context = message(user_id=99999)
    if user == "missing":
        update.effective_user = None
    context.application.bot_data["pending_task_1"] = {"title": "Fictional", "notes": "Fictional"}
    with patch.object(api, "create_task") as create, patch.object(api, "list_open_tasks") as read, \
         patch("handlers.capture.classify") as classify:
        await (main.on_message if entry == "on_message" else getattr(tasks, entry))(update, context)
    create.assert_not_called()
    read.assert_not_called()
    classify.assert_not_called()
    assert len(context.application.bot_data) == 1
    assert store.recent() == []
    update.message.reply_text.assert_not_awaited()
    update.callback_query.answer.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["task_add:1", "task_skip:1"])
async def test_confirm_or_skip_then_duplicate_has_at_most_one_write(action):
    update, context = message()
    await tasks.command_add(update, context)
    pending = dict(context.application.bot_data["pending_task_1"])
    update.callback_query.data = action
    with patch.object(api, "create_task", return_value={"id": "fictional"}) as create:
        await tasks.handle_callback(update, context)
        await tasks.handle_callback(update, context)
    if action.startswith("task_add"):
        create.assert_called_once_with(pending["title"], pending["notes"])
    else:
        create.assert_not_called()
    assert context.application.bot_data == {}
    assert len(store.recent()) == 1
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_overlapping_confirmations_and_loop_responsiveness():
    update, context = message()
    await tasks.command_add(update, context)
    entered, finish = threading.Event(), threading.Event()

    def slow_insert(*args):
        entered.set()
        assert finish.wait(2)
        return {"id": "fictional"}

    with patch.object(api, "create_task", side_effect=slow_insert) as create:
        first = asyncio.create_task(tasks.handle_callback(update, context))
        try:
            for _ in range(200):
                if entered.is_set():
                    break
                await asyncio.sleep(.001)
            assert entered.is_set(), "Insertion did not run in a worker"
            await tasks.handle_callback(update, context)
            create.assert_called_once()
            assert not first.done()
        finally:
            finish.set()
            await first


@pytest.mark.asyncio
async def test_uncertain_write_and_reply_failure_never_retries_or_logs_details(caplog):
    update, context = message()
    await tasks.command_add(update, context)
    update.callback_query.edit_message_text.side_effect = TelegramError("PRIVATE_FICTIONAL_REPLY")
    with patch.object(api, "create_task", side_effect=RuntimeError("PRIVATE_FICTIONAL_GOOGLE")) as create:
        await tasks.handle_callback(update, context)
        await tasks.handle_callback(update, context)
    create.assert_called_once()
    assert "Check Google Tasks" in update.callback_query.edit_message_text.call_args.args[0]
    assert "PRIVATE_FICTIONAL" not in caplog.text


@pytest.mark.asyncio
async def test_cancelled_insert_consumes_confirmation():
    update, context = message()
    await tasks.command_add(update, context)
    with patch.object(tasks.asyncio, "to_thread", new_callable=AsyncMock, side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await tasks.handle_callback(update, context)
    assert context.application.bot_data == {}
    with patch.object(api, "create_task") as create:
        await tasks.handle_callback(update, context)
    create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["task_delete:1", "task_add:abc", "task_add:", "task_add:1:2", "task_add:１２"])
async def test_invalid_callbacks_do_not_consume_pending(data):
    update, context = message()
    await tasks.command_add(update, context)
    update.callback_query.data = data
    with patch.object(api, "create_task") as create:
        await tasks.handle_callback(update, context)
    create.assert_not_called()
    assert "pending_task_1" in context.application.bot_data


@pytest.mark.asyncio
async def test_restart_expires_buttons_without_recreating_task():
    update, context = message()
    with patch.object(api, "create_task") as create:
        await tasks.handle_callback(update, context)
    create.assert_not_called()
    assert "expired" in update.callback_query.answer.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["add", "list"])
async def test_authorization_error_is_sanitized(operation):
    update, context = message()
    await tasks.command_add(update, context)
    with patch.object(api, "create_task", side_effect=TasksAuthorizationRequired()), \
         patch.object(api, "list_open_tasks", side_effect=TasksAuthorizationRequired()):
        await (tasks.handle_callback if operation == "add" else tasks.command_list)(update, context)
    reply = (update.callback_query.edit_message_text if operation == "add" else update.message.reply_text)
    assert "auth_tasks.py" in reply.call_args.args[0]
    assert "Calendar settings were preserved" in reply.call_args.args[0]


@pytest.mark.asyncio
async def test_long_capture_stays_local_without_incomplete_preview():
    update, context = message("/task " + "x" * 3000)
    await tasks.command_add(update, context)
    assert len(store.recent()) == 1
    assert context.application.bot_data == {}
    assert "Nothing added" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_unicode_preview_respects_telegram_utf16_limit():
    update, context = message("/task " + "🌷" * 1800)
    await tasks.command_add(update, context)
    body = update.message.reply_text.call_args.args[0]
    assert len(body.encode("utf-16-le")) // 2 <= 4096
    assert not context.application.bot_data


@pytest.mark.asyncio
async def test_malformed_success_is_reported_as_uncertain_without_retry():
    update, context = message()
    await tasks.command_add(update, context)
    with patch.object(api, "create_task", return_value={}) as create:
        await tasks.handle_callback(update, context)
        await tasks.handle_callback(update, context)
    create.assert_called_once()
    assert "Could not confirm" in update.callback_query.edit_message_text.call_args.args[0]


@pytest.mark.asyncio
async def test_large_unicode_task_list_fits_a_telegram_reply():
    update, context = message("/tasks")
    items = [{"title": "🌷" * 120, "due": "2026-11-12T00:00:00Z"} for _ in range(20)]
    with patch.object(api, "list_open_tasks", return_value=(items, True)):
        await tasks.command_list(update, context)
    body = update.message.reply_text.call_args.args[0]
    assert len(body.encode("utf-16-le")) // 2 <= 4096


@pytest.mark.asyncio
async def test_preview_failure_drops_pending_without_logging_content(caplog):
    update, context = message()
    update.message.reply_text.side_effect = TelegramError("PRIVATE_FICTIONAL_REPLY")
    await tasks.command_add(update, context)
    assert context.application.bot_data == {}
    assert "PRIVATE_FICTIONAL" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["/tasks", "List my tasks", "Show my Google tasks"])
async def test_list_routing_plain_rendering_and_limit(text):
    update, context = message(text)
    items = [{"title": "Fictional [cards]*", "due": "2026-11-12T00:00:00.000Z"}]
    with patch.object(api, "list_open_tasks", return_value=(items, True)) as read, \
         patch("handlers.capture.classify") as classify:
        await (tasks.command_list if text.startswith("/") else main.on_message)(update, context)
    read.assert_called_once()
    classify.assert_not_called()
    args = update.message.reply_text.call_args
    assert "Fictional [cards]* — due 2026-11-12" in args.args[0]
    assert "More tasks exist" in args.args[0]
    assert not args.kwargs.get("parse_mode")
    assert store.recent() == []


def test_google_insert_contract_and_no_due_or_retries():
    with patch.object(api, "_service") as service:
        api.create_task("Fictional cards", "Buy fictional cards tomorrow")
    insert = service.return_value.tasks.return_value.insert
    insert.assert_called_once_with(tasklist="@default", body={
        "title": "Fictional cards", "notes": "Buy fictional cards tomorrow"})
    insert.return_value.execute.assert_called_once_with(num_retries=0)


def test_list_pagination_gets_open_task_on_second_page():
    with patch.object(api, "_service") as service:
        call = service.return_value.tasks.return_value.list
        call.return_value.execute.side_effect = [
            {"items": [{"title": "Done fictional", "status": "completed"}], "nextPageToken": "fictional2"},
            {"items": [{"title": "Fictional cards", "status": "needsAction"}]},
        ]
        found, more = api.list_open_tasks()
    assert [t["title"] for t in found] == ["Fictional cards"]
    assert not more
    assert call.call_args_list[1].kwargs["pageToken"] == "fictional2"
    for item in call.call_args_list:
        assert item.kwargs["showCompleted"] is False
        assert item.kwargs["tasklist"] == "@default"


def test_list_repeated_marker_is_rejected():
    with patch.object(api, "_service") as service:
        service.return_value.tasks.return_value.list.return_value.execute.return_value = {
            "nextPageToken": "fictional-repeat"}
        with pytest.raises(RuntimeError, match="pagination"):
            api.list_open_tasks()


def test_service_has_bounded_transport():
    with patch.object(api, "get_credentials") as get, patch.object(api.httplib2, "Http") as http, \
         patch.object(api, "AuthorizedHttp") as transport, patch.object(api, "build") as build:
        api._service()
    http.assert_called_once_with(timeout=30)
    transport.assert_called_once_with(get.return_value, http=http.return_value)
    build.assert_called_once_with("tasks", "v1", http=transport.return_value, cache_discovery=False)
