import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from db.store import Capture, save
import dates
from handlers import date_clarification as clarification
from handlers import query as query_handler
from handlers import tasks as tasks_handler
from handlers import drive as drive_handler
from handlers.google.calendar import format_iso_dt
from llm.classifier import Classified, ClassifierError, classify

_ICONS = {"note": "📝", "link": "🔗", "event": "📅", "task": "✅", "image": "🖼️"}


def _md_safe(text: str) -> str:
    """Escape MarkdownV1 special characters in user-provided text."""
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


def _confirm(result: Classified, row_id: int) -> str:
    icon = _ICONS.get(result.type, "💾")
    lines = [f"{icon} Saved as **{result.type}**"]
    if result.title:
        lines.append(f"Title: {_md_safe(result.title)}")
    if result.url:
        lines.append(f"URL: {_md_safe(result.url)}")
    if result.description:
        lines.append(f"Note: {_md_safe(result.description)}")
    lines.append(f"_(#{row_id})_")
    return "\n".join(lines)


def _event_prompt(result: Classified, row_id: int) -> str:
    lines = [f"📅 Saved as **event** _(#{row_id})_"]
    if result.title:
        lines.append(_md_safe(result.title))
    if result.event_dt:
        lines.append(format_iso_dt(result.event_dt))
    lines.append("")
    lines.append("Add to Google Calendar?")
    return "\n".join(lines)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    if not text:
        return

    reference = dates.now_local()
    pending = clarification.take(context)
    if text.lower() == "cancel":
        await update.message.reply_text("Date clarification cancelled." if pending else "Nothing to clarify.")
        return
    if pending and clarification.expired(pending, reference):
        await update.message.reply_text("That clarification expired. Please resend the full message.")
        return

    answer = ""
    if pending:
        answer = "\n".join(filter(None, [pending["answer"], text]))
        text, reference = pending["text"], pending["now"]
        if pending["kind"] == "query":
            await query_handler._calendar_query(update, context, text, now=reference, answer=answer)
            return
        result = pending["result"]
    else:
        if drive_handler.explicit_content(text) is not None:
            await drive_handler.command_add(update, context)
            return
        if tasks_handler.is_list_request(text):
            await tasks_handler.command_list(update, context)
            return
        task_text = tasks_handler.explicit_task(text)
        if task_text is not None:
            if not task_text:
                await update.message.reply_text("Use Task: Buy fictional index cards. Nothing added.")
                return
            text = task_text
            result = Classified(type="task", title=text[:1024])
        else:
            if query_handler.is_capture_search(text) or dates.calendar_question(text):
                await query_handler.handle(update, context, text, now=reference)
                return
            try:
                result = await asyncio.to_thread(classify, text, now=reference)
            except ClassifierError as exc:
                await update.message.reply_text(f"⚠️ Could not classify your message: {exc}")
                return

        if result.type == "query":
            await query_handler.handle(update, context, text, now=reference)
            return

    if result.type == "event":
        try:
            resolved = dates.resolve_event(text, reference, answer=answer)
        except dates.ClarificationNeeded as exc:
            await clarification.ask(
                update, context, kind="event", text=text, now=reference,
                question=str(exc), result=result, answer=answer,
            )
            return
        result = result.model_copy(update={"event_dt": resolved})

    capture = Capture(
        type=result.type,
        raw=text,
        title=result.title,
        url=result.url,
        event_dt=result.event_dt,
    )
    row_id = save(capture)

    if result.type == "task":
        await tasks_handler.preview(update, context, title=result.title or text[:1024],
                                    notes=text, row_id=row_id)
    elif result.type == "event" and result.event_dt:
        context.application.bot_data[f"pending_cal_{row_id}"] = {
            "title": result.title or text[:50],
            "event_dt": result.event_dt,
            "description": result.description,
        }
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✓ Add to Calendar", callback_data=f"cal_add:{row_id}"),
            InlineKeyboardButton("✗ Skip", callback_data=f"cal_skip:{row_id}"),
        ]])
        await update.message.reply_text(
            _event_prompt(result, row_id),
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(_confirm(result, row_id), parse_mode="Markdown")
