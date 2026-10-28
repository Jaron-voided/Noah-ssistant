"""Caption-sorted Telegram photos; download/upload only after explicit Save."""
import asyncio
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from db.store import Capture, save
from handlers.auth_guard import auth
from handlers.google import drive as api
from handlers.google.drive_auth import DriveAuthorizationRequired
from private_paths import PrivatePathError

log = logging.getLogger(__name__)
MAX_PHOTO_BYTES = 10 * 1024 * 1024
_LABEL = re.compile(r"\s*category\s*:\s*([A-Za-z][A-Za-z0-9_-]{0,23})\s*", re.I)
_TAG = re.compile(r"(?<!\S)#(\S+)")
_CATEGORY = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,23}")


def category_from_caption(caption):
    """Only explicit category lines/tags or the supported meme/fitness labels."""
    category_lines = [line for line in caption.splitlines() if re.match(r"\s*category\s*:", line, re.I)]
    if category_lines:
        matches = [_LABEL.fullmatch(line) for line in category_lines]
        if not all(matches):
            return None
        labels = {m[1].lower() for m in matches}
        return next(iter(labels)) if len(labels) == 1 else None
    raw_tags = [m[1].rstrip(".,!?;:") for m in _TAG.finditer(caption)]
    if any(not _CATEGORY.fullmatch(tag) for tag in raw_tags):
        return None
    tags = {tag.lower() for tag in raw_tags}
    if tags:
        return next(iter(tags)) if len(tags) == 1 else None
    simple = re.fullmatch(r"\s*(meme|fitness)(?:\s*:.*)?\s*", caption, re.I | re.S)
    return simple[1].lower() if simple else None


@auth
async def handle_photo(update, context):
    photos = update.message.photo or []
    if not photos:
        return
    photo = photos[-1]  # highest-resolution Telegram photo variant
    caption = update.message.caption or ""
    category = category_from_caption(caption)
    row_id = save(Capture(type="image", raw=caption or "Telegram photo", title="Telegram photo",
                          metadata={"source": "telegram_photo", "category": category}))
    # No image bytes, Telegram file IDs or model-generated labels go into SQLite.
    if photo.file_size and photo.file_size > MAX_PHOTO_BYTES:
        await update.message.reply_text(f"Image saved locally as metadata (#{row_id}). Demo photo limit is 10 MiB; nothing uploaded.", parse_mode=None)
        return
    name = f"noah-image-{row_id}.jpg"
    target = "Noah Inbox / Images" + (f" / {category}" if category else "")
    preview = (f"🖼️ Image capture (#{row_id}) — upload this photo to Google Drive?\n"
               f"Folder: My Drive / {target}\nFile: {name}\n"
               f"Category: {category or 'not specified or unclear; use Images'}\n"
               f"Caption: {caption or '(none)'}\n\n"
               "Save creates missing folders and uploads the Telegram JPEG. No visual analysis or sharing changes.")
    if len(preview.encode("utf-16-le")) // 2 > 1000:
        await update.message.reply_text(f"Image metadata saved locally (#{row_id}). Caption is too long for a complete preview; resend with a shorter caption. Nothing uploaded.", parse_mode=None)
        return
    key = f"pending_photo_{row_id}"
    context.application.bot_data[key] = {
        "file_id": photo.file_id, "name": name, "category": category, "caption": caption,
    }
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✓ Upload photo to Drive", callback_data=f"photo_add:{row_id}"),
        InlineKeyboardButton("✗ Skip", callback_data=f"photo_skip:{row_id}"),
    ]])
    try:
        # Reuse Telegram's cached file for the preview; do not download photo bytes.
        await update.message.reply_photo(photo=photo.file_id, caption=preview, reply_markup=keyboard, parse_mode=None)
    except TelegramError:
        context.application.bot_data.pop(key, None)
        log.warning("Photo preview could not be delivered; no download or Drive upload attempted.")


async def _edit(query, text):
    try:
        # Photo previews need caption edits, not edit_message_text.
        await query.edit_message_caption(caption=text, parse_mode=None)
    except TelegramError:
        log.warning("Photo result reply could not be delivered; check Drive before another upload.")


@auth
async def handle_callback(update, context):
    query = update.callback_query
    if query is None:
        return
    action, _, raw_id = (query.data or "").partition(":")
    if action not in ("photo_add", "photo_skip") or not raw_id.isascii() or not raw_id.isdecimal():
        await query.answer("Invalid photo action.")
        return
    pending = context.application.bot_data.pop(f"pending_photo_{int(raw_id)}", None)
    if pending is None:
        await query.answer("This upload was already handled or expired.")
        return
    try:
        await query.answer()
    except TelegramError:
        await _edit(query, "Confirmation could not be acknowledged. Nothing uploaded; resend if needed.")
        return
    if action == "photo_skip":
        await _edit(query, "Skipped photo upload. Local caption/category metadata is saved; no photo bytes downloaded.")
        return
    data = None
    uploading = False
    try:
        file = await context.bot.get_file(pending["file_id"], read_timeout=30, connect_timeout=5)
        if file.file_size and file.file_size > MAX_PHOTO_BYTES:
            await _edit(query, "Photo exceeds the 10 MiB demo limit. Nothing uploaded.")
            return
        data = await file.download_as_bytearray(read_timeout=30, connect_timeout=5)
        if not data or len(data) > MAX_PHOTO_BYTES:
            await _edit(query, "Photo is empty or exceeds the 10 MiB demo limit. Nothing uploaded.")
            return
        uploading = True
        result = await asyncio.to_thread(api.save_photo, name=pending["name"], content=bytes(data),
                                         category=pending["category"], caption=pending["caption"])
        file_id = result.get("id")
        if not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
            raise RuntimeError("Invalid Drive upload result.")
    except asyncio.CancelledError:
        log.warning("Photo operation interrupted; check Drive before another upload.")
        raise
    except (DriveAuthorizationRequired, PrivatePathError) as exc:
        text = str(exc)
    except Exception:
        text = ("Could not confirm whether the photo upload completed. Check Noah Inbox / Images in Drive before another upload."
                if uploading else "Could not download this Telegram photo. Nothing uploaded to Drive; resend if needed.")
    else:
        target = "Noah Inbox / Images" + (f" / {pending['category']}" if pending["category"] else "")
        text = f"🖼️ Uploaded to {target}\nhttps://drive.google.com/file/d/{file_id}/view"
    finally:
        if isinstance(data, bytearray):
            data.clear()
    await _edit(query, text)
