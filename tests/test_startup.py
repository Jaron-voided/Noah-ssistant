"""Exercise PTB's real polling lifecycle without network calls or a database."""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

from telegram.ext import Application, Updater

import main
from handlers import tasks, drive, photos


def test_transport_info_logs_cannot_expose_bot_request_urls(caplog):
    with caplog.at_level(logging.INFO):
        logging.getLogger("httpx").info("PRIVATE_BOT_REQUEST_URL")
        logging.getLogger("httpcore").info("PRIVATE_BOT_REQUEST_URL")
    assert "PRIVATE_BOT_REQUEST_URL" not in caplog.text


def test_startup_without_current_event_loop(monkeypatch):
    asyncio.set_event_loop(None)
    app = Application.builder().token("123456:dummy-test-token").build()
    builder = MagicMock()
    builder.token.return_value.build.return_value = app
    monkeypatch.setattr(main.Application, "builder", lambda: builder)
    init_db = MagicMock()
    monkeypatch.setattr(main, "init_db", init_db)
    initialize = AsyncMock()
    polling = AsyncMock()
    shutdown = AsyncMock()
    loops = []

    async def start():
        loop = asyncio.get_running_loop()
        loops.append(loop)
        loop.call_later(0.01, loop.stop)

    monkeypatch.setattr(Application, "initialize", initialize)
    monkeypatch.setattr(Application, "start", start_mock := AsyncMock(side_effect=start))
    monkeypatch.setattr(Application, "shutdown", shutdown)
    monkeypatch.setattr(Updater, "start_polling", polling)

    main.main()

    init_db.assert_called_once_with()
    initialize.assert_awaited_once()
    polling.assert_awaited_once()
    assert polling.call_args.kwargs["drop_pending_updates"] is True
    start_mock.assert_awaited_once()
    shutdown.assert_awaited_once()
    assert len(loops) == 1
    assert loops[0].is_closed()


def test_demo_commands_and_callbacks_are_registered(monkeypatch):
    app = Application.builder().token("123456:dummy-test-token").build()
    builder = MagicMock()
    builder.token.return_value.build.return_value = app
    monkeypatch.setattr(main.Application, "builder", lambda: builder)
    monkeypatch.setattr(main, "init_db", MagicMock())
    monkeypatch.setattr(Application, "run_polling", MagicMock())
    main.main()
    from telegram.ext import CommandHandler, CallbackQueryHandler

    commands = {command: handler.callback for handler in app.handlers[0]
                if isinstance(handler, CommandHandler) for command in handler.commands}
    assert commands["task"] is tasks.command_add
    assert commands["tasks"] is tasks.command_list
    assert commands["drive"] is drive.command_add
    assert commands["today"] is main.cmd_today
    callbacks = [h for h in app.handlers[0] if isinstance(h, CallbackQueryHandler)]
    assert any(h.pattern.match("task_add:1") and h.callback is tasks.handle_callback for h in callbacks)
    assert any(h.pattern.match("drive_add:1") and h.callback is drive.handle_callback for h in callbacks)
    assert any(h.pattern.match("photo_add:1") and h.callback is photos.handle_callback for h in callbacks)
    from telegram.ext import MessageHandler
    assert any(isinstance(h, MessageHandler) and h.callback is photos.handle_photo for h in app.handlers[0])
    from datetime import datetime, timezone
    from telegram import Chat, Message, PhotoSize, Update, User
    photo_update = Update(1, message=Message(
        message_id=1, date=datetime(2026, 10, 27, tzinfo=timezone.utc),
        chat=Chat(1, "private"), from_user=User(12345, "Fictional", False),
        photo=[PhotoSize("fictional-file", "fictional-unique", 10, 10, file_size=20)]))
    assert any(isinstance(h, MessageHandler) and h.callback is photos.handle_photo
               and h.check_update(photo_update) for h in app.handlers[0])
