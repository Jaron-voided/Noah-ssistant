import asyncio
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from db.store import init_db
from handlers import capture as capture_handler
from handlers import query as query_handler
from handlers import tasks as tasks_handler
from handlers import drive as drive_handler
from handlers import photos as photos_handler
from handlers.auth_guard import auth
from handlers.calendar_confirm import handle_callback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
# HTTPX's INFO request URLs include the Telegram bot token. Keep transport
# request logging disabled during ordinary bot operation.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger(__name__)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log diagnostic locations, never updates, locals, or exception messages.

    Transport exceptions may contain token-bearing URLs or private API data;
    ordinary exc_info/traceback formatting would include that exception text.
    """
    error = context.error
    frames = []
    tb = error.__traceback__ if error is not None else None
    while tb is not None:
        code = tb.tb_frame.f_code
        frames.append(f"{Path(code.co_filename).name}:{tb.tb_lineno}:{code.co_name}")
        tb = tb.tb_next
    kind = "background"
    update_id = None
    if isinstance(update, Update):
        update_id = update.update_id
        kind = "callback" if update.callback_query is not None else "message" if update.message is not None else "other"
    log.error("Unhandled bot error: type=%s update_id=%s kind=%s stack=%s",
              type(error).__name__, update_id, kind, " -> ".join(frames[-12:]) or "unavailable")


@auth
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Hi, I'm Noah.\n\n"
        "Send me anything and I'll capture it — notes, links, tasks, events.\n\n"
        "Commands:\n"
        "/today — today's calendar\n"
        "/week  — next 7 days\n"
        "/task <text> — preview a Google Task\n"
        "/tasks — open tasks in your default list\n"
        "/drive <text or link> — preview a Drive save\n"
        "Send a photo — preview a confirmed Drive upload; caption meme or fitness to sort\n"
        "/help  — this message"
        "\nFind <keywords> — search saved captures",
        parse_mode=None,
    )


@auth
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await query_handler._calendar_query(update, context, "today")


@auth
async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await query_handler._calendar_query(update, context, "next 7 days")


@auth
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await capture_handler.handle_message(update, context)


def main() -> None:
    init_db()
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("task", tasks_handler.command_add))
    app.add_handler(CommandHandler("tasks", tasks_handler.command_list))
    app.add_handler(CommandHandler("drive", drive_handler.command_add))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(MessageHandler(filters.PHOTO, photos_handler.handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^cal_(add|skip):"))
    app.add_handler(CallbackQueryHandler(tasks_handler.handle_callback, pattern=r"^task_(add|skip):"))
    app.add_handler(CallbackQueryHandler(drive_handler.handle_callback, pattern=r"^drive_(add|skip):"))
    app.add_handler(CallbackQueryHandler(photos_handler.handle_callback, pattern=r"^photo_(add|skip):"))
    log.info("Noah is running (long polling) — authorized user: %d", config.TELEGRAM_USER_ID)
    # Python 3.14 no longer creates the loop expected by python-telegram-bot 21.6.
    with asyncio.Runner() as runner:
        runner.get_loop()
        app.run_polling(drop_pending_updates=True, close_loop=False)


if __name__ == "__main__":
    main()
