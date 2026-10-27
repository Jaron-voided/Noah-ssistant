"""Short-lived, per-user clarification state; no Calendar write authorization."""
from datetime import timedelta, timezone


KEY = "pending_date_clarification"


def take(context):
    return context.user_data.pop(KEY, None)


def expired(pending, now):
    elapsed = now.astimezone(timezone.utc) - pending["now"].astimezone(timezone.utc)
    return elapsed > timedelta(minutes=10)


async def ask(update, context, *, kind, text, now, question, result=None, answer=""):
    context.user_data[KEY] = {
        "kind": kind, "text": text, "now": now, "result": result, "answer": answer,
    }
    await update.message.reply_text(f"{question}\nReply to clarify, or send cancel.")
