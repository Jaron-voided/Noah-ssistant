"""Explicit text/link export; Google writes require the preview's Save button."""
import asyncio
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.error import TelegramError

from db.store import Capture, save
from handlers.auth_guard import auth
from handlers.google import drive as api
from handlers.google.drive_auth import DriveAuthorizationRequired
from private_paths import PrivatePathError

log = logging.getLogger(__name__)
_PREFIX = re.compile(r"\s*(?:drive|save\s+to\s+drive)\s*:\s*(.*)", re.I | re.S)
_URL = re.compile(r"https?://[^\s]+", re.I)


def explicit_content(text):
    match = _PREFIX.fullmatch(text)
    return match[1].strip() if match else None


@auth
async def command_add(update, context):
    text = explicit_content(update.message.text or "")
    if text is None:
        text = (update.message.text or "").partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("Use /drive https://example.com or Drive: Fictional orchid notes. I will preview the save.")
        return
    url = _URL.search(text)
    category = "Links" if url else "Notes"
    title = re.sub(r"[\r\n/\\]", "-", text.splitlines()[0][:70]).strip() or "Noah capture"
    name = title + ".txt"
    row_id = save(Capture(type="link" if url else "note", raw=text, title=title,
                          url=url[0] if url else None))
    preview = (f"💾 Saved locally (#{row_id}). Save a copy to Google Drive?\n"
               f"Folder: My Drive / Noah Inbox / {category}\nFile: {name}\n\n{text}\n\n"
               "Creates the folders if missing and a new plain-text file. Does not fetch links or change sharing.")
    if len(preview.encode("utf-16-le")) // 2 > 4000:
        await update.message.reply_text(f"Saved locally (#{row_id}). Too long for a complete Drive preview; send shorter text. Nothing uploaded.")
        return
    key = f"pending_drive_{row_id}"
    context.application.bot_data[key] = {"name": name, "content": text, "category": category}
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✓ Save to Google Drive", callback_data=f"drive_add:{row_id}"),
        InlineKeyboardButton("✗ Skip", callback_data=f"drive_skip:{row_id}"),
    ]])
    try:
        await update.message.reply_text(preview, reply_markup=keyboard,
                                        link_preview_options=LinkPreviewOptions(is_disabled=True))
    except TelegramError:
        context.application.bot_data.pop(key, None)
        log.warning("Drive preview could not be delivered; no Google write attempted.")


async def _edit(query, text):
    try:
        await query.edit_message_text(text, link_preview_options=LinkPreviewOptions(is_disabled=True))
    except TelegramError:
        log.warning("Drive result reply could not be delivered; check Drive before another save.")


@auth
async def handle_callback(update, context):
    query = update.callback_query
    if query is None:
        return
    action, _, raw_id = (query.data or "").partition(":")
    if action not in ("drive_add", "drive_skip") or not raw_id.isascii() or not raw_id.isdecimal():
        await query.answer("Invalid Drive action.")
        return
    pending = context.application.bot_data.pop(f"pending_drive_{int(raw_id)}", None)
    if pending is None:
        await query.answer("This save was already handled or expired.")
        return
    try:
        await query.answer()
    except TelegramError:
        await _edit(query, "Confirmation could not be acknowledged. Nothing uploaded; resend if needed.")
        return
    if action == "drive_skip":
        await _edit(query, "Skipped Google Drive save. Your local capture is saved.")
        return
    try:
        result = await asyncio.to_thread(api.save_text, **pending)
        file_id = result.get("id")
        if not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
            raise RuntimeError("Missing Drive creation result.")
    except asyncio.CancelledError:
        log.warning("Drive save interrupted; check Drive before another save.")
        raise
    except (DriveAuthorizationRequired, PrivatePathError) as exc:
        text = str(exc)
    except Exception:
        text = ("Could not confirm whether this save completed. Check Noah Inbox in Google Drive "
                "before starting another save; folders or a file may already exist.")
    else:
        text = (f"💾 Saved to Noah Inbox / {pending['category']}\n{pending['name']}\n"
                f"https://drive.google.com/file/d/{file_id}/view")
    await _edit(query, text)
