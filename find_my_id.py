"""
Run this once to discover your Telegram user ID, then add it to .env.

    python find_my_id.py

Send any message to your bot in Telegram. This script prints the sender's
numeric user ID and exits. Paste that number as TELEGRAM_USER_ID in .env.
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("ERROR: TELEGRAM_BOT_TOKEN is not set in .env or your environment.")


async def main():
    from telegram import Update
    from telegram.ext import Application, MessageHandler, filters, ContextTypes

    print("Waiting for a message from your Telegram account…")
    print(f"Open Telegram, find your bot (@...) and send it any message.")

    found = asyncio.Event()

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        name = update.effective_user.full_name
        print(f"\n✓ Your Telegram user ID is: {uid}  (name: {name})")
        print(f"\nAdd this line to your .env file:")
        print(f"  TELEGRAM_USER_ID={uid}")
        found.set()
        await context.application.stop()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.ALL, on_message))

    async with app:
        await app.updater.start_polling(drop_pending_updates=True)
        await app.start()
        await found.wait()
        await app.updater.stop()


asyncio.run(main())
