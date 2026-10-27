import logging
import asyncio

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from handlers.auth_guard import auth
from handlers.google import calendar as cal
from handlers.google.calendar import format_iso_dt
from handlers.google.auth import AuthorizationRequired
from private_paths import PrivatePathError

log = logging.getLogger(__name__)


async def _edit_result(query, text: str) -> None:
    try:
        # Plain text avoids interpreting untrusted event titles as Markdown.
        await query.edit_message_text(text)
    except TelegramError:
        # The Calendar request may already have succeeded. Never invite a retry
        # merely because Telegram could not display the result, or log its data.
        log.warning("Calendar confirmation reply could not be delivered.")


@auth
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return

    data = query.data or ""
    action, _, raw_id = data.partition(":")
    if action not in ("cal_add", "cal_skip") or not raw_id.isascii() or not raw_id.isdecimal():
        await query.answer("Invalid Calendar action.")
        return

    key = f"pending_cal_{int(raw_id)}"
    pending_events = context.application.bot_data
    if key not in pending_events:
        # Do not overwrite a previous success/skip reply on a repeated tap.
        await query.answer("This addition was already handled or has expired.")
        return

    await query.answer()
    # Claim before the insert or any result-reply await. Another callback must
    # never reuse this addition, even if the API result or Telegram reply fails.
    pending = pending_events.pop(key, None)
    if not pending:
        return

    if action == "cal_add":
        try:
            display = format_iso_dt(pending["event_dt"])
            event = await asyncio.to_thread(
                cal.create_event,
                summary=pending["title"],
                start_dt=pending["event_dt"],
                description=pending.get("description"),
            )
        except asyncio.CancelledError:
            log.warning("Calendar request interrupted; check Calendar before another addition.")
            raise
        except (AuthorizationRequired, PrivatePathError) as exc:
            text = str(exc)
        except FileNotFoundError:
            text = "Google Calendar is not set up. Existing authorization settings were preserved."
        except Exception:
            text = (
                "Could not confirm whether this event was added. "
                "Check Google Calendar before starting another addition."
            )
        else:
            link = event.get("htmlLink", "")
            text = f"✅ Added to Google Calendar\n{pending['title']}\n{display}"
            if link:
                text += f"\nOpen in Calendar: {link}"
        await _edit_result(query, text)
    else:
        original = query.message.text or ""
        await _edit_result(query, original + "\n\n(Not added to Calendar)")
