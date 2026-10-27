import asyncio
import logging

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


@auth
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Hi, I'm Noah.\n\n"
        "Send me anything and I'll capture it — notes, links, tasks, events.\n\n"
        "Commands:\n"
        "/today — today's calendar\n"
        "/week  — next 7 days\n"
        "/help  — this message"
        "\nFind <keywords> — search saved captures"
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
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^cal_(add|skip):"))
    log.info("Noah is running (long polling) — authorized user: %d", config.TELEGRAM_USER_ID)
    # Python 3.14 no longer creates the loop expected by python-telegram-bot 21.6.
    with asyncio.Runner() as runner:
        runner.get_loop()
        app.run_polling(drop_pending_updates=True, close_loop=False)


if __name__ == "__main__":
    main()
