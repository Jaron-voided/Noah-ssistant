"""Telegram Tasks preview/confirmation. All public entry points are authorized."""
import asyncio
import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions
from telegram.error import TelegramError

from db.store import Capture, save
from handlers.auth_guard import auth
from handlers.google import tasks as api
from handlers.google.tasks_auth import TasksAuthorizationRequired
from private_paths import PrivatePathError

log = logging.getLogger(__name__)
_LIST = re.compile(r"\s*(?:list|show)(?:\s+me)?\s+(?:my\s+)?(?:google\s+)?tasks[.!?]?\s*", re.I)
_CAPTURE = re.compile(r"\s*(?:task\s*:|add\s+(?:a\s+)?task\s*:)\s*(.*)", re.I | re.S)


def is_list_request(text):
    return _LIST.fullmatch(text) is not None


def explicit_task(text):
    match = _CAPTURE.fullmatch(text)
    return match[1].strip() if match else None


@auth
async def command_add(update, context):
    text = (update.message.text or "").partition(" ")[2].strip()
    if not text:
        await update.message.reply_text("Use /task Buy fictional index cards. I will preview it before adding anything.")
        return
    row_id = save(Capture(type="task", raw=text, title=text[:1024]))
    await preview(update, context, title=text[:1024], notes=text, row_id=row_id)


async def preview(update, context, *, title, notes, row_id):
    text = (f"✅ Saved locally as task (#{row_id})\n\nAdd to Google Tasks?\n"
            f"List: your default Google Tasks list\nTitle: {title}\nNotes: {notes}\n"
            "Due date/reminder: not set. Date/time words remain notes only.")
    if len(title) > 1024 or len(notes) > 2500 or len(text.encode("utf-16-le")) // 2 > 4000:
        await update.message.reply_text(
            f"Saved locally as task (#{row_id}). Too long for a complete task preview; "
            "send a shorter task (up to 2500 characters). Nothing added to Google Tasks."
        )
        return
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✓ Add to Google Tasks", callback_data=f"task_add:{row_id}"),
        InlineKeyboardButton("✗ Skip", callback_data=f"task_skip:{row_id}"),
    ]])
    key = f"pending_task_{row_id}"
    context.application.bot_data[key] = {"title": title, "notes": notes}
    try:
        await update.message.reply_text(text, reply_markup=keyboard,
                                        link_preview_options=LinkPreviewOptions(is_disabled=True))
    except TelegramError:
        context.application.bot_data.pop(key, None)
        log.warning("Task preview could not be delivered; no Google write attempted.")


async def _edit(query, text):
    try:
        await query.edit_message_text(text, link_preview_options=LinkPreviewOptions(is_disabled=True))
    except TelegramError:
        log.warning("Task result reply could not be delivered; check Tasks before another addition.")


@auth
async def handle_callback(update, context):
    query = update.callback_query
    if query is None:
        return
    action, _, raw_id = (query.data or "").partition(":")
    if action not in ("task_add", "task_skip") or not raw_id.isascii() or not raw_id.isdecimal():
        await query.answer("Invalid Tasks action.")
        return
    pending = context.application.bot_data.pop(f"pending_task_{int(raw_id)}", None)
    if pending is None:
        await query.answer("This task was already handled or expired.")
        return
    # Claim synchronously, before any await. Duplicate callbacks cannot insert.
    try:
        await query.answer()
    except TelegramError:
        await _edit(query, "Confirmation could not be acknowledged. Nothing added; resend the task if needed.")
        return
    if action == "task_skip":
        await _edit(query, "Skipped Google Tasks addition. Your local capture is saved.")
        return
    try:
        result = await asyncio.to_thread(api.create_task, pending["title"], pending["notes"])
        if not isinstance(result, dict) or not isinstance(result.get("id"), str) or not result["id"]:
            raise RuntimeError("Missing Tasks insertion result.")
    except asyncio.CancelledError:
        log.warning("Tasks insertion interrupted; check Tasks before another addition.")
        raise
    except (TasksAuthorizationRequired, PrivatePathError) as exc:
        text = str(exc)
    except Exception:
        text = "Could not confirm whether this task was added. Check Google Tasks before starting another addition."
    else:
        text = f"✅ Added to Google Tasks (default list)\n{pending['title']}"
    await _edit(query, text)


@auth
async def command_list(update, context):
    try:
        tasks, more = await asyncio.to_thread(api.list_open_tasks)
    except (TasksAuthorizationRequired, PrivatePathError) as exc:
        await update.message.reply_text(str(exc))
        return
    except Exception:
        await update.message.reply_text("Could not read Google Tasks. Check API access and setup privately, then try again.")
        return
    lines = ["✅ Open tasks — default Google Tasks list (up to 20)"]
    for task in tasks:
        title = (task.get("title") or "(untitled)")[:80]
        # Google exposes date-only due values; never imply a reminder time.
        due = str(task.get("due") or "")[:10]
        lines.append(f"• {title}" + (f" — due {due}" if due else ""))
    if not tasks:
        lines.append("No open tasks in this list.")
    if more:
        lines.append("More tasks exist. Open Google Tasks to see the rest.")
    await update.message.reply_text("\n".join(lines), link_preview_options=LinkPreviewOptions(is_disabled=True))
