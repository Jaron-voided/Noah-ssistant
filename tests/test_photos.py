"""Only fictional Telegram IDs/bytes and mocked Drive services."""
import asyncio
import json
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import TelegramError

import config
from db import store
from handlers import photos
from handlers import date_clarification
from handlers.google import drive as api
from handlers.google.drive_auth import DriveAuthorizationRequired


@pytest.fixture(autouse=True)
def local_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "fictional.db")
    store.init_db()


def message(caption="", user_id=None):
    update, context = MagicMock(), MagicMock()
    update.effective_user.id = config.TELEGRAM_USER_ID if user_id is None else user_id
    update.message.caption = caption
    update.message.photo = [MagicMock(file_id="fictional-small", file_size=4),
                            MagicMock(file_id="fictional-large", file_size=20)]
    update.message.reply_text = AsyncMock()
    update.message.reply_photo = AsyncMock()
    update.callback_query.data = "photo_add:1"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_caption = AsyncMock()
    context.user_data = {}
    context.application.bot_data = {}
    file = MagicMock(file_size=20)
    file.download_as_bytearray = AsyncMock(side_effect=lambda **kw: bytearray(b"fictional photo bytes"))
    context.bot.get_file = AsyncMock(return_value=file)
    return update, context


@pytest.mark.parametrize("caption,expected", [
    ("meme", "meme"), ("fitness", "fitness"), ("MEME: fictional caption", "meme"),
    ("Fictional caption #fitness", "fitness"), ("Category: travel\nFictional scene", "travel"),
    ("Category: meme\nfictional #fitness", "meme"),
    ("", None), ("Fictional mountains", None), ("not a meme", None),
    ("meme fitness", None), ("#meme #fitness", None),
    ("category: meme\ncategory: fitness", None), ("category: ../private", None),
    ("category: meme\ncategory: ???", None), ("category: ???\n#meme", None),
    ("#abcdefghijklmnopqrstuvwx-more", None), ("https://example.com/#meme", None),
])
def test_caption_sorting_requires_explicit_unambiguous_category(caption, expected):
    assert photos.category_from_caption(caption) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("caption,folder", [("", "Noah Inbox / Images"), ("meme", "Images / meme"),
                                             ("#fitness", "Images / fitness"), ("#meme #fitness", "Noah Inbox / Images")])
async def test_photo_recognized_previewed_without_download_or_drive_call(caption, folder):
    update, context = message(caption)
    with patch.object(api, "save_photo") as save:
        await photos.handle_photo(update, context)
    save.assert_not_called()
    context.bot.get_file.assert_not_awaited()
    preview = update.message.reply_photo.call_args.kwargs
    assert preview["photo"] == "fictional-large"
    assert folder in preview["caption"]
    assert "No visual analysis" in preview["caption"]
    assert [b.callback_data for b in preview["reply_markup"].inline_keyboard[0]] == [
        "photo_add:1", "photo_skip:1"]
    record = store.recent()[0]
    assert record["type"] == "image"
    assert json.loads(record["metadata"])["category"] == photos.category_from_caption(caption)
    assert "fictional-large" not in str(record)
    assert "fictional photo bytes" not in str(record)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["photo", "callback"])
@pytest.mark.parametrize("missing", [True, False])
async def test_unauthorized_photo_or_callback_cannot_download_save_reply_or_consume(entry, missing):
    update, context = message("meme", user_id=99999)
    if missing:
        update.effective_user = None
    context.application.bot_data["pending_photo_1"] = {"file_id": "fictional-file"}
    with patch.object(api, "save_photo") as save:
        await (photos.handle_photo if entry == "photo" else photos.handle_callback)(update, context)
    save.assert_not_called()
    context.bot.get_file.assert_not_awaited()
    update.message.reply_photo.assert_not_awaited()
    update.message.reply_text.assert_not_awaited()
    update.callback_query.answer.assert_not_awaited()
    assert len(context.application.bot_data) == 1
    assert store.recent() == []


@pytest.mark.asyncio
async def test_skip_never_downloads_or_uploads_and_keeps_local_metadata():
    update, context = message("meme")
    await photos.handle_photo(update, context)
    update.callback_query.data = "photo_skip:1"
    with patch.object(api, "save_photo") as save:
        await photos.handle_callback(update, context)
        await photos.handle_callback(update, context)
    save.assert_not_called()
    context.bot.get_file.assert_not_awaited()
    assert len(store.recent()) == 1
    assert not context.application.bot_data


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["add", "skip"])
async def test_photo_preserves_other_confirmations_and_date_clarification(action):
    update, context = message("meme")
    other = {"pending_cal_77": {"title": "Fictional Calendar"},
             "pending_task_78": {"title": "Fictional Tasks"},
             "pending_drive_79": {"name": "Fictional.txt"}}
    clarification = {"kind": "event", "text": "Fictional meeting tomorrow at 5", "answer": ""}
    context.application.bot_data.update(other)
    context.user_data[date_clarification.KEY] = clarification
    await photos.handle_photo(update, context)
    update.callback_query.data = f"photo_{action}:1"
    with patch.object(api, "save_photo", return_value={"id": "fictional-upload"}), \
         patch.object(api, "save_text") as text_upload, \
         patch("handlers.google.calendar.create_event") as calendar, \
         patch("handlers.google.tasks.create_task") as tasks:
        await photos.handle_callback(update, context)
    assert context.application.bot_data == other
    assert context.user_data[date_clarification.KEY] is clarification
    text_upload.assert_not_called()
    calendar.assert_not_called()
    tasks.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_uploads_exact_photo_once_and_clears_download_buffer():
    update, context = message("fitness")
    data = bytearray(b"fictional photo bytes")
    context.bot.get_file.return_value.download_as_bytearray = AsyncMock(return_value=data)
    await photos.handle_photo(update, context)
    with patch.object(api, "save_photo", return_value={"id": "fictional-upload"}) as save:
        await photos.handle_callback(update, context)
        await photos.handle_callback(update, context)
    context.bot.get_file.assert_awaited_once_with("fictional-large", read_timeout=30, connect_timeout=5)
    save.assert_called_once_with(name="noah-image-1.jpg", content=b"fictional photo bytes", category="fitness", caption="fitness")
    assert data == bytearray()
    update.callback_query.edit_message_caption.assert_awaited_once()
    assert "Images / fitness" in update.callback_query.edit_message_caption.call_args.kwargs["caption"]
    assert not context.application.bot_data


@pytest.mark.asyncio
async def test_overlapping_confirmations_while_downloading_do_not_duplicate():
    update, context = message()
    await photos.handle_photo(update, context)
    entered, finish = asyncio.Event(), asyncio.Event()

    async def download(**kwargs):
        entered.set()
        await finish.wait()
        return bytearray(b"fictional photo bytes")

    context.bot.get_file.return_value.download_as_bytearray.side_effect = download
    with patch.object(api, "save_photo", return_value={"id": "fictional-upload"}) as save:
        first = asyncio.create_task(photos.handle_callback(update, context))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await photos.handle_callback(update, context)
            save.assert_not_called()
        finally:
            finish.set()
            await first
    save.assert_called_once()
    context.bot.get_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_worker_cancellation_never_retries_and_loop_remains_responsive():
    update, context = message()
    await photos.handle_photo(update, context)
    entered, finish = threading.Event(), threading.Event()

    def upload(**kwargs):
        entered.set()
        assert finish.wait(2)
        return {"id": "fictional-upload"}

    with patch.object(api, "save_photo", side_effect=upload) as save:
        first = asyncio.create_task(photos.handle_callback(update, context))
        try:
            for _ in range(200):
                if entered.is_set():
                    break
                await asyncio.sleep(.001)
            assert entered.is_set()
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            await photos.handle_callback(update, context)
            save.assert_called_once()
        finally:
            finish.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["metadata", "download", "upload", "authorization", "result"])
async def test_failures_sanitized_no_automatic_retry(stage, caplog):
    update, context = message("Fictional caption")
    await photos.handle_photo(update, context)
    failure = RuntimeError("PRIVATE_FICTIONAL_DETAIL")
    if stage == "metadata":
        context.bot.get_file.side_effect = failure
    if stage == "download":
        context.bot.get_file.return_value.download_as_bytearray.side_effect = failure
    with patch.object(api, "save_photo", return_value={"id": "fictional-upload"}) as save:
        if stage == "upload":
            save.side_effect = failure
        if stage == "authorization":
            save.side_effect = DriveAuthorizationRequired()
        if stage == "result":
            save.return_value = {}
        await photos.handle_callback(update, context)
        await photos.handle_callback(update, context)
    assert save.call_count <= 1
    reply = update.callback_query.edit_message_caption.call_args.kwargs["caption"]
    assert "PRIVATE_FICTIONAL" not in reply + caplog.text
    if stage in ("metadata", "download"):
        save.assert_not_called()
        assert "Nothing uploaded" in reply
    elif stage == "authorization":
        assert "auth_drive.py" in reply
    else:
        assert "Check Noah Inbox" in reply


@pytest.mark.asyncio
async def test_preview_delivery_failure_retains_no_uploadable_pending_photo(caplog):
    update, context = message()
    update.message.reply_photo.side_effect = TelegramError("PRIVATE_FICTIONAL_PHOTO_URL")
    await photos.handle_photo(update, context)
    assert not context.application.bot_data
    context.bot.get_file.assert_not_awaited()
    assert "PRIVATE_FICTIONAL" not in caplog.text


@pytest.mark.asyncio
async def test_success_reply_failure_never_restores_confirmation(caplog):
    update, context = message()
    await photos.handle_photo(update, context)
    update.callback_query.edit_message_caption.side_effect = TelegramError("PRIVATE_FICTIONAL_PHOTO_URL")
    with patch.object(api, "save_photo", return_value={"id": "fictional-upload"}) as save:
        await photos.handle_callback(update, context)
        await photos.handle_callback(update, context)
    save.assert_called_once()
    assert "PRIVATE_FICTIONAL" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["capture", "metadata", "bytes"])
async def test_photo_size_limit_blocks_upload(stage):
    update, context = message()
    if stage == "capture":
        update.message.photo[-1].file_size = photos.MAX_PHOTO_BYTES + 1
    await photos.handle_photo(update, context)
    if stage == "metadata":
        context.bot.get_file.return_value.file_size = photos.MAX_PHOTO_BYTES + 1
    if stage == "bytes":
        context.bot.get_file.return_value.download_as_bytearray.side_effect = lambda **kw: bytearray(photos.MAX_PHOTO_BYTES + 1)
    with patch.object(api, "save_photo") as save:
        await photos.handle_callback(update, context)
    save.assert_not_called()
    assert not context.application.bot_data


@pytest.mark.asyncio
async def test_long_caption_does_not_offer_incomplete_preview():
    update, context = message("🌷" * 600)
    await photos.handle_photo(update, context)
    update.message.reply_photo.assert_not_awaited()
    assert not context.application.bot_data
    assert "shorter caption" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_invalid_and_restart_callbacks_do_not_download():
    update, context = message()
    await photos.handle_callback(update, context)
    update.callback_query.data = "photo_add:abc"
    await photos.handle_callback(update, context)
    context.bot.get_file.assert_not_awaited()


@pytest.mark.parametrize("category,parent", [(None, "fictional-images"), ("meme", "fictional-memes")])
def test_drive_photo_uses_images_and_explicit_category(category, parent):
    with patch.object(api, "_service") as service:
        files = service.return_value.files.return_value
        files.list.return_value.execute.side_effect = [
            {"files": [{"id": "fictional-root"}]}, {"files": [{"id": "fictional-images"}]},
            {"files": [{"id": "fictional-memes"}]}]
        files.create.return_value.execute.return_value = {"id": "fictional-upload"}
        api.save_photo(name="fictional.jpg", content=b"fictional JPEG", category=category, caption="Fictional")
    create = files.create.call_args.kwargs
    assert create["body"] == {"name": "fictional.jpg", "mimeType": "image/jpeg", "parents": [parent], "description": "Fictional"}
    assert create["media_body"].getbytes(0, 100) == b"fictional JPEG"
    assert create["media_body"].resumable() is False
    assert files.list.call_count == (3 if category else 2)
    assert "name = 'Images'" in files.list.call_args_list[1].kwargs["q"]
    files.create.return_value.execute.assert_called_once_with(num_retries=0)
    service.return_value.permissions.assert_not_called()


@pytest.mark.parametrize("category", ["../private", "meme' or trashed=true", "meme/fitness", ""])
def test_unsafe_category_cannot_enter_a_drive_query(category):
    with patch.object(api, "_service") as service:
        with pytest.raises(ValueError):
            api.save_photo(name="fictional.jpg", content=b"fictional JPEG", category=category)
    service.assert_not_called()
