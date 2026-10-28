"""Short-lived, per-user clarification state; no Calendar write authorization."""
from datetime import timedelta, timezone
from dates import ClarificationValues


KEY = "pending_date_clarification"


def take(context):
    return context.user_data.pop(KEY, None)


def expired(pending, now):
    elapsed = now.astimezone(timezone.utc) - pending["now"].astimezone(timezone.utc)
    return elapsed > timedelta(minutes=10)


async def ask(update, context, *, kind, text, now, question, result=None, values=None, attempts=0):
    if attempts >= 4:
        take(context)
        await update.message.reply_text(
            "I couldn't resolve that date/time after four replies. This clarification is closed; "
            "please resend the full message with MM-DD-YYYY and an explicit time, "
            "for example: Meeting 10-29-2026 at 5pm (or all day). Nothing added to Calendar.",
            parse_mode=None,
        )
        return
    context.user_data[KEY] = {
        "kind": kind, "text": text, "now": now, "result": result,
        "values": values if values is not None else ClarificationValues(),
        "attempts": attempts,
    }
    await update.message.reply_text(f"{question}\nReply to clarify, or send cancel.", parse_mode=None)
