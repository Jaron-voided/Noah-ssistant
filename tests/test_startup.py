"""Exercise PTB's real polling lifecycle without network calls or a database."""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

from telegram.ext import Application, Updater

import main


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
