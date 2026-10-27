"""Fictional Drive exports and mocked responses; never fetch supplied URLs."""
import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import TelegramError

import config
import main
from db import store
from handlers import drive
from handlers.google import drive as api
from handlers.google.drive_auth import DriveAuthorizationRequired


@pytest.fixture(autouse=True)
def local_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "fictional.db")
    store.init_db()


def message(text="/drive Fictional orchid notes", user_id=None):
    update, context = MagicMock(), MagicMock()
    update.effective_user.id = config.TELEGRAM_USER_ID if user_id is None else user_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.callback_query.data = "drive_add:1"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    context.user_data = {}
    context.application.bot_data = {}
    return update, context


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["/drive ", "Drive: ", "Save to Drive: "])
@pytest.mark.parametrize("content,category", [
    ("Fictional orchid notes", "Notes"), ("Fictional guide https://example.com/orchids", "Links")])
async def test_capture_exact_preview_local_save_no_model_or_remote_call(prefix, content, category):
    update, context = message(prefix + content)
    with patch.object(api, "save_text") as save, patch("handlers.capture.classify") as model:
        await (drive.command_add if prefix.startswith("/") else main.on_message)(update, context)
    save.assert_not_called()
    model.assert_not_called()
    row = store.recent()[0]
    assert row["raw"] == content
    assert row["type"] == ("link" if category == "Links" else "note")
    pending = context.application.bot_data["pending_drive_1"]
    assert pending["category"] == category
    assert pending["content"] == content
    args = update.message.reply_text.call_args
    assert content in args.args[0]
    assert "Noah Inbox / " + category in args.args[0]
    assert pending["name"] in args.args[0]
    assert "Creates the folders if missing" in args.args[0]
    assert not args.kwargs.get("parse_mode")
    assert args.kwargs["link_preview_options"].is_disabled is True
    assert [b.callback_data for b in args.kwargs["reply_markup"].inline_keyboard[0]] == [
        "drive_add:1", "drive_skip:1"]


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["command", "message", "callback"])
@pytest.mark.parametrize("missing", [False, True])
async def test_unauthorized_users_cannot_write_reply_or_consume(entry, missing):
    update, context = message(user_id=99999)
    if missing:
        update.effective_user = None
    context.application.bot_data["pending_drive_1"] = {"content": "Fictional"}
    handler = {"command": drive.command_add, "message": main.on_message, "callback": drive.handle_callback}[entry]
    with patch.object(api, "save_text") as save:
        await handler(update, context)
    save.assert_not_called()
    assert len(context.application.bot_data) == 1
    assert store.recent() == []
    update.message.reply_text.assert_not_awaited()
    update.callback_query.answer.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["add", "skip"])
async def test_confirmation_or_skip_then_duplicate(action):
    update, context = message()
    await drive.command_add(update, context)
    original = dict(context.application.bot_data["pending_drive_1"])
    update.callback_query.data = "drive_" + action + ":1"
    with patch.object(api, "save_text", return_value={"id": "fictional-file"}) as save:
        await drive.handle_callback(update, context)
        await drive.handle_callback(update, context)
    if action == "add":
        save.assert_called_once_with(**original)
        assert "https://drive.google.com/file/d/fictional-file/view" in update.callback_query.edit_message_text.call_args.args[0]
        assert update.callback_query.edit_message_text.call_args.kwargs["link_preview_options"].is_disabled is True
    else:
        save.assert_not_called()
    update.callback_query.edit_message_text.assert_awaited_once()
    assert context.application.bot_data == {}


@pytest.mark.asyncio
async def test_overlap_keeps_loop_responsive_and_only_one_save():
    update, context = message()
    await drive.command_add(update, context)
    entered, finish = threading.Event(), threading.Event()

    def slow(**kwargs):
        entered.set()
        assert finish.wait(2)
        return {"id": "fictional-file"}

    with patch.object(api, "save_text", side_effect=slow) as save:
        first = asyncio.create_task(drive.handle_callback(update, context))
        try:
            for _ in range(200):
                if entered.is_set():
                    break
                await asyncio.sleep(.001)
            assert entered.is_set()
            await drive.handle_callback(update, context)
            save.assert_called_once()
            assert not first.done()
        finally:
            finish.set()
            await first


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("PRIVATE_FICTIONAL_GOOGLE"), DriveAuthorizationRequired()])
async def test_errors_are_sanitized_and_preview_never_retried(failure, caplog):
    update, context = message()
    await drive.command_add(update, context)
    with patch.object(api, "save_text", side_effect=failure) as save:
        await drive.handle_callback(update, context)
        await drive.handle_callback(update, context)
    save.assert_called_once()
    reply = update.callback_query.edit_message_text.call_args.args[0]
    assert "PRIVATE_FICTIONAL" not in reply + caplog.text
    assert "auth_drive.py" in reply if isinstance(failure, DriveAuthorizationRequired) else "Check Noah Inbox" in reply


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_result", [{}, {"id": "https://fictional.invalid"}, None])
async def test_malformed_save_result_is_uncertain(bad_result):
    update, context = message()
    await drive.command_add(update, context)
    with patch.object(api, "save_text", return_value=bad_result):
        await drive.handle_callback(update, context)
    assert "Could not confirm" in update.callback_query.edit_message_text.call_args.args[0]
    assert not context.application.bot_data


@pytest.mark.asyncio
async def test_failed_preview_discards_buttons_and_retains_local_capture(caplog):
    update, context = message()
    update.message.reply_text.side_effect = TelegramError("PRIVATE_FICTIONAL_REPLY")
    await drive.command_add(update, context)
    assert not context.application.bot_data
    assert len(store.recent()) == 1
    assert "PRIVATE_FICTIONAL" not in caplog.text


@pytest.mark.asyncio
async def test_lost_success_reply_does_not_repeat_save(caplog):
    update, context = message()
    await drive.command_add(update, context)
    update.callback_query.edit_message_text.side_effect = TelegramError("PRIVATE_FICTIONAL_REPLY")
    with patch.object(api, "save_text", return_value={"id": "fictional-file"}) as save:
        await drive.handle_callback(update, context)
        await drive.handle_callback(update, context)
    save.assert_called_once()
    assert "PRIVATE_FICTIONAL" not in caplog.text


@pytest.mark.asyncio
async def test_cancelled_save_consumes_confirmation():
    update, context = message()
    await drive.command_add(update, context)
    with patch.object(drive.asyncio, "to_thread", new_callable=AsyncMock, side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await drive.handle_callback(update, context)
    assert not context.application.bot_data


@pytest.mark.asyncio
async def test_restart_and_invalid_actions_never_upload():
    update, context = message()
    with patch.object(api, "save_text") as save:
        await drive.handle_callback(update, context)
        update.callback_query.data = "drive_add:abc"
        await drive.handle_callback(update, context)
    save.assert_not_called()


@pytest.mark.asyncio
async def test_unicode_text_not_partially_previewed_or_uploaded():
    update, context = message("/drive " + "🌷" * 2100)
    await drive.command_add(update, context)
    assert not context.application.bot_data
    assert "Nothing uploaded" in update.message.reply_text.call_args.args[0]
    assert len(store.recent()) == 1


def test_reuses_tagged_folders_and_uploads_exact_bytes_without_fetch_or_share():
    content = "Fictional https://example.com/?q=orchids\nUntrusted ' text [notes]"
    with patch.object(api, "_service") as service:
        files = service.return_value.files.return_value
        files.list.return_value.execute.side_effect = [
            {"files": [{"id": "fictional-root"}]}, {"files": [{"id": "fictional-links"}]}]
        files.create.return_value.execute.return_value = {"id": "fictional-file"}
        assert api.save_text(name="Fictional.txt", content=content, category="Links") == {"id": "fictional-file"}
    files.create.assert_called_once()
    args = files.create.call_args.kwargs
    assert args["body"] == {"name": "Fictional.txt", "mimeType": "text/plain", "parents": ["fictional-links"]}
    assert args["media_body"].getbytes(0, len(content.encode())) == content.encode()
    assert args["media_body"].resumable() is False
    files.create.return_value.execute.assert_called_once_with(num_retries=0)
    assert "orchids" not in str(files.list.call_args_list)
    assert "name = 'Noah Inbox'" in files.list.call_args_list[0].kwargs["q"]
    assert "name = 'Links'" in files.list.call_args_list[1].kwargs["q"]
    service.return_value.permissions.assert_not_called()


def test_new_save_creates_only_expected_folders_then_file():
    with patch.object(api, "_service") as service:
        files = service.return_value.files.return_value
        files.list.return_value.execute.return_value = {"files": []}
        files.create.return_value.execute.side_effect = [
            {"id": "fictional-root"}, {"id": "fictional-notes"}, {"id": "fictional-file"}]
        api.save_text(name="Fictional.txt", content="Fictional notes", category="Notes")
    calls = files.create.call_args_list
    assert len(calls) == 3
    assert calls[0].kwargs["body"]["name"] == "Noah Inbox"
    assert calls[0].kwargs["body"]["parents"] == ["root"]
    assert calls[1].kwargs["body"]["name"] == "Notes"
    assert calls[1].kwargs["body"]["parents"] == ["fictional-root"]
    assert calls[2].kwargs["body"]["parents"] == ["fictional-notes"]
    assert all(c.kwargs == {"num_retries": 0} for c in files.create.return_value.execute.call_args_list)


def test_folder_lookup_follows_pages_and_detects_duplicate_roots():
    files = MagicMock()
    files.list.return_value.execute.side_effect = [
        {"files": [{"id": "fictional-root"}], "nextPageToken": "fictional-next"},
        {"files": [{"id": "fictional-duplicate"}]}]
    with pytest.raises(RuntimeError, match="Multiple Noah"):
        api._folder(files, "inbox", "Noah Inbox")
    files.create.assert_not_called()
    assert files.list.call_args_list[1].kwargs["pageToken"] == "fictional-next"


def test_folder_lookup_repeated_marker_rejected():
    files = MagicMock()
    files.list.return_value.execute.return_value = {"nextPageToken": "fictional-repeat"}
    with pytest.raises(RuntimeError, match="pagination"):
        api._folder(files, "inbox", "Noah Inbox")


def test_invalid_parent_not_interpolated_into_query():
    files = MagicMock()
    with pytest.raises(RuntimeError, match="metadata"):
        api._folder(files, "notes", "Notes", "fictional' or trashed=true")
    files.list.assert_not_called()


def test_partial_save_failure_is_not_retried():
    with patch.object(api, "_service") as service:
        files = service.return_value.files.return_value
        files.list.return_value.execute.return_value = {"files": []}
        files.create.return_value.execute.side_effect = [{"id": "fictional-root"}, RuntimeError("fictional failure")]
        with pytest.raises(RuntimeError):
            api.save_text(name="Fictional.txt", content="Fictional notes", category="Notes")
    assert files.create.call_count == 2


def test_service_has_bounded_transport():
    with patch.object(api, "get_credentials") as get, patch.object(api.httplib2, "Http") as http, \
         patch.object(api, "AuthorizedHttp") as transport, patch.object(api, "build") as build:
        api._service()
    http.assert_called_once_with(timeout=30)
    transport.assert_called_once_with(get.return_value, http=http.return_value)
    build.assert_called_once_with("drive", "v3", http=transport.return_value, cache_discovery=False)
