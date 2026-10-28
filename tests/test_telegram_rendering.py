"""Exercise real PTB serialization/defaults; Telegram transport stays mocked."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from telegram import CallbackQuery, Chat, Message, PhotoSize, Update, User
from telegram.ext import Defaults, ExtBot

import config
import dates
from db.store import init_db, recent
from handlers.capture import handle_message
from handlers import date_clarification
from llm.classifier import Classified


NOW = datetime(2026, 10, 28, 12, tzinfo=ZoneInfo("America/New_York"))
SPECIAL = r"Planning_team *draft* [review](link) `code` \ <b>R&D</b>!"


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "fictional.db")
    monkeypatch.setattr(config, "TIMEZONE", "America/New_York")
    monkeypatch.setattr(dates, "now_local", lambda: NOW)
    init_db()


def incoming(bot, text, **kwargs):
    message = Message(1, NOW, Chat(12345, "private"),
                      from_user=User(12345, "Fictional", False), text=text, **kwargs)
    message.set_bot(bot)
    return Update(77, message=message)


def context():
    return SimpleNamespace(user_data={}, application=SimpleNamespace(bot_data={}))


def reply_payload(post):
    assert post.call_args.kwargs["endpoint"] == "sendMessage"
    payload = post.call_args.kwargs["data"]
    assert "parse_mode" not in payload
    assert "entities" not in payload
    return payload


# _do_post is after PTB inserts Defaults and removes None values. No HTTP.
RESPONSE = {"message_id": 2, "date": int(NOW.timestamp()),
            "chat": {"id": 12345, "type": "private"}, "text": "Fictional response"}


@pytest.mark.asyncio
@pytest.mark.parametrize("default_mode", [None, "Markdown", "MarkdownV2", "HTML"])
async def test_event_preview_is_literal_even_with_application_defaults(default_mode):
    bot = ExtBot("123456:dummy-test-token", defaults=Defaults(parse_mode=default_mode))
    state = context()
    with patch.object(ExtBot, "_do_post", new_callable=AsyncMock, return_value=RESPONSE) as post, \
         patch("handlers.capture.classify", return_value=Classified(type="event", title=SPECIAL, description=SPECIAL)), \
         patch("handlers.google.calendar.create_event") as create:
        await handle_message(incoming(bot, "Meeting tomorrow at 5pm"), state)
    payload = reply_payload(post)
    assert SPECIAL in payload["text"]
    assert "America/New_York" in payload["text"]
    assert "**event**" not in payload["text"]
    row = recent()[0]
    assert payload["reply_markup"].inline_keyboard[0][0].callback_data == f"cal_add:{row['id']}"
    assert state.application.bot_data[f"pending_cal_{row['id']}"]["description"] == SPECIAL
    create.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("default_mode", ["MarkdownV2", "HTML"])
async def test_capture_description_and_url_are_literal(default_mode):
    bot = ExtBot("123456:dummy-test-token", defaults=Defaults(parse_mode=default_mode))
    url = "https://example.com/a_b?q=[draft]&view=full"
    with patch.object(ExtBot, "_do_post", new_callable=AsyncMock, return_value=RESPONSE) as post, \
         patch("handlers.capture.classify", return_value=Classified(type="link", title=SPECIAL, description=SPECIAL, url=url)):
        await handle_message(incoming(bot, "A fictional link"), context())
    payload = reply_payload(post)
    assert f"Title: {SPECIAL}" in payload["text"]
    assert f"Note: {SPECIAL}" in payload["text"]
    assert url in payload["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["event", "query"])
async def test_special_characters_in_clarification_question_and_full_reply(kind):
    bot = ExtBot("123456:dummy-test-token", defaults=Defaults(parse_mode="MarkdownV2"))
    state = context()
    original = "Meeting tonmorow" if kind == "event" else "Show calendar"
    with patch.object(ExtBot, "_do_post", new_callable=AsyncMock, return_value=RESPONSE) as post, \
         patch("handlers.google.calendar.create_event") as create, \
         patch("handlers.google.calendar.events_for_range", return_value=[]):
        await date_clarification.ask(incoming(bot, original), state, kind=kind,
                                     text=original, now=NOW, question=f"What date? {SPECIAL}",
                                     result=Classified(type="event", title=SPECIAL, description=SPECIAL))
        assert SPECIAL in reply_payload(post)["text"]
        await handle_message(incoming(bot, f"{SPECIAL} 10/29/26 5pm"), state)
        payload = reply_payload(post)
    assert "2026-10-29" in payload["text"]
    assert not state.user_data
    create.assert_not_called()
    if kind == "event":
        assert SPECIAL in payload["text"] and "reply_markup" in payload


@pytest.mark.asyncio
async def test_calendar_response_renders_untrusted_google_title_literally():
    bot = ExtBot("123456:dummy-test-token", defaults=Defaults(parse_mode="HTML"))
    with patch.object(ExtBot, "_do_post", new_callable=AsyncMock, return_value=RESPONSE) as post, \
         patch("handlers.google.calendar.events_for_range", return_value=[
             {"summary": SPECIAL, "start": {"date": "2026-10-29"}, "end": {"date": "2026-10-30"}},
         ]):
        await handle_message(incoming(bot, "Show calendar tomorrow"), context())
    assert SPECIAL in reply_payload(post)["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize("flow", ["task", "drive", "photo", "calendar_edit", "task_edit", "drive_edit", "photo_edit"])
async def test_other_previews_and_callback_results_override_html_defaults(flow):
    from handlers import calendar_confirm, drive, photos, tasks

    bot = ExtBot("123456:dummy-test-token", defaults=Defaults(parse_mode="HTML"))
    update = incoming(bot, f"/drive {SPECIAL}")
    callback = CallbackQuery("fictional-callback", User(12345, "Fictional", False), "fictional-chat", message=update.message)
    callback.set_bot(bot)
    with patch.object(ExtBot, "_do_post", new_callable=AsyncMock, return_value=RESPONSE) as post:
        if flow == "task":
            await tasks.preview(update, context(), title=SPECIAL, notes=SPECIAL, row_id=1)
        elif flow == "drive":
            await drive.command_add(update, context())
        elif flow == "photo":
            update = incoming(bot, None, caption=SPECIAL,
                              photo=[PhotoSize("fictional-photo", "fictional-unique", 10, 10, file_size=20)])
            await photos.handle_photo(update, context())
        else:
            edit = {"calendar_edit": calendar_confirm._edit_result, "task_edit": tasks._edit,
                    "drive_edit": drive._edit, "photo_edit": photos._edit}[flow]
            await edit(callback, SPECIAL)
    data = post.call_args.kwargs["data"]
    assert "parse_mode" not in data
    assert SPECIAL in data.get("text", data.get("caption", ""))


@pytest.mark.asyncio
async def test_explicit_calendar_add_preserves_literal_title_and_description():
    from handlers.calendar_confirm import handle_callback

    bot = ExtBot("123456:dummy-test-token", defaults=Defaults(parse_mode="MarkdownV2"))
    state = context()
    state.application.bot_data["pending_cal_1"] = {
        "title": SPECIAL, "description": SPECIAL, "event_dt": "2026-10-29T17:00:00-04:00",
    }
    query = CallbackQuery("fictional-callback", User(12345, "Fictional", False), "fictional-chat",
                          data="cal_add:1", message=incoming(bot, "Preview").message)
    query.set_bot(bot)
    with patch.object(ExtBot, "_do_post", new_callable=AsyncMock, return_value=RESPONSE) as post, \
         patch("handlers.google.calendar.create_event", return_value={}) as create:
        await handle_callback(Update(78, callback_query=query), state)
    create.assert_called_once_with(summary=SPECIAL, start_dt="2026-10-29T17:00:00-04:00", description=SPECIAL)
    data = post.call_args.kwargs["data"]
    assert "parse_mode" not in data and SPECIAL in data["text"]
    assert not state.application.bot_data
