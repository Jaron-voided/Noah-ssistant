from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import config
import dates
from db.store import init_db, recent
from handlers.capture import handle_message
from handlers import query
from llm.classifier import Classified, classify


NOW = datetime(2026, 10, 27, 12, 15, tzinfo=ZoneInfo("America/New_York"))


@pytest.fixture(autouse=True)
def isolated_clock_and_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "America/New_York")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(dates, "now_local", lambda: NOW)
    init_db()
    with patch("handlers.google.calendar._service", side_effect=AssertionError("Live Calendar is forbidden in tests")):
        yield


def make_update(text):
    update, context = MagicMock(), MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    context.user_data = {}
    context.application.bot_data = {}
    return update, context


@pytest.mark.asyncio
async def test_wrong_model_date_is_ignored_and_exact_preview_requires_confirmation():
    update, context = make_update("Fictional meeting tomorrow at 5pm")
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Fictional meeting", event_dt="1999-01-01")), \
         patch("handlers.google.calendar.create_event") as create:
        await handle_message(update, context)
    create.assert_not_called()
    assert recent()[0]["event_dt"] == "2026-10-28T17:00:00-04:00"
    preview = update.message.reply_text.call_args.args[0]
    assert "2026-10-28" in preview and "5:00 PM" in preview
    assert "America/New_York" in preview and "EDT" in preview
    assert update.message.reply_text.call_args.kwargs["reply_markup"]


@pytest.mark.asyncio
async def test_clarification_never_saves_or_offers_add_until_time_is_explicit():
    update, context = make_update("Fictional meeting tomorrow at 5")
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Fictional meeting")) as model, \
         patch("handlers.google.calendar.create_event") as create:
        await handle_message(update, context)
        assert "AM or PM" in update.message.reply_text.call_args.args[0]
        assert not recent() and not context.application.bot_data
        assert "reply_markup" not in update.message.reply_text.call_args.kwargs
        update.message.text = "5pm"
        await handle_message(update, context)
    model.assert_called_once()
    create.assert_not_called()
    assert recent()[0]["event_dt"] == "2026-10-28T17:00:00-04:00"
    assert len(context.application.bot_data) == 1


@pytest.mark.asyncio
async def test_multi_step_week_clarification_and_all_day():
    update, context = make_update("Fictional workshop next week")
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Fictional workshop")):
        await handle_message(update, context)
        assert "Which date" in update.message.reply_text.call_args.args[0]
        update.message.text = "Friday"
        await handle_message(update, context)
        assert "What time" in update.message.reply_text.call_args.args[0]
        update.message.text = "all day"
        await handle_message(update, context)
    assert recent()[0]["event_dt"] == "2026-11-06"
    assert "all day" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["cancel", "expired"])
async def test_cancel_or_expired_clarification_cannot_create_pending_addition(reply, monkeypatch):
    update, context = make_update("Fictional meeting tomorrow")
    with patch("handlers.capture.classify", return_value=Classified(type="event")):
        await handle_message(update, context)
        if reply == "expired":
            monkeypatch.setattr(dates, "now_local", lambda: NOW + timedelta(minutes=11))
            update.message.text = "5pm"
        else:
            update.message.text = reply
        await handle_message(update, context)
    assert not recent() and not context.application.bot_data and not context.user_data


@pytest.mark.asyncio
async def test_tomorrow_calendar_question_uses_resolved_bounds_not_today_or_model():
    update, context = make_update("What's on my calendar tomorrow?")
    with patch("handlers.capture.classify") as model, \
         patch("handlers.google.calendar.events_for_range", return_value=[]) as read:
        await handle_message(update, context)
    model.assert_not_called()
    start, end = read.call_args.args
    assert start.isoformat() == "2026-10-28T00:00:00-04:00"
    assert end.isoformat() == "2026-10-29T00:00:00-04:00"
    assert "2026-10-28 00:00 EDT" in update.message.reply_text.call_args.args[0]
    assert "America/New_York" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_vague_calendar_question_can_be_clarified_without_api_call_first():
    update, context = make_update("What's on my calendar?")
    with patch("handlers.google.calendar.events_for_range", return_value=[]) as read:
        await handle_message(update, context)
        read.assert_not_called()
        update.message.text = "next week"
        await handle_message(update, context)
    start, end = read.call_args.args
    assert start.date().isoformat() == "2026-11-02"
    assert end.date().isoformat() == "2026-11-09"
    assert not recent() and not context.application.bot_data


@pytest.mark.asyncio
async def test_all_day_query_filters_timed_events():
    update, context = make_update("Show all-day events tomorrow")
    with patch("handlers.google.calendar.events_for_range", return_value=[
        {"summary": "Fictional workshop", "start": {"date": "2026-10-28"}},
        {"summary": "Fictional timed meeting", "start": {"dateTime": "2026-10-28T17:00:00-04:00"}},
    ]):
        await handle_message(update, context)
    response = update.message.reply_text.call_args.args[0]
    assert "Fictional workshop" in response and "Fictional timed meeting" not in response


def test_classifier_receives_the_same_fixed_clock_and_timezone():
    with patch("llm.classifier.requests.post") as post:
        post.return_value.json.return_value = {"message": {"content": '{"type":"event"}'}}
        classify("Fictional meeting tomorrow at 5pm", now=NOW)
    system = post.call_args.kwargs["json"]["messages"][0]["content"]
    assert NOW.isoformat() in system and "America/New_York" in system


@pytest.mark.parametrize("start, expected_end", [
    ("2026-11-01T01:30:00-04:00", "2026-11-01T01:30:00-05:00"),
    ("2026-03-08T01:30:00-05:00", "2026-03-08T03:30:00-04:00"),
])
def test_confirmed_payload_and_preview_agree_across_dst(start, expected_end):
    from handlers.google import calendar as cal
    from datetime import timezone

    with patch("handlers.google.calendar._service") as service:
        cal.create_event("Fictional meeting", start)
    body = service.return_value.events.return_value.insert.call_args.kwargs["body"]
    assert body["end"]["dateTime"] == expected_end
    actual_start = datetime.fromisoformat(body["start"]["dateTime"])
    actual_end = datetime.fromisoformat(body["end"]["dateTime"])
    assert (actual_end.astimezone(timezone.utc) - actual_start.astimezone(timezone.utc)).total_seconds() == 3600
    assert "EDT" in cal.format_iso_dt(start) and "EST" in cal.format_iso_dt(start)


@pytest.mark.asyncio
async def test_timed_question_filters_at_the_instant_without_inventing_duration():
    update, context = make_update("What's on my calendar tomorrow at 5pm?")
    with patch("handlers.google.calendar.events_for_range", return_value=[
        {"summary": "Active fictional meeting", "start": {"dateTime": "2026-10-28T17:00:00-04:00"},
         "end": {"dateTime": "2026-10-28T18:00:00-04:00"}},
        {"summary": "Finished fictional meeting", "start": {"dateTime": "2026-10-28T16:00:00-04:00"},
         "end": {"dateTime": "2026-10-28T17:00:00-04:00"}},
        {"summary": "Future fictional meeting", "start": {"dateTime": "2026-10-28T18:00:00-04:00"},
         "end": {"dateTime": "2026-10-28T19:00:00-04:00"}},
        {"summary": "Active all-day fictional event", "start": {"date": "2026-10-28"},
         "end": {"date": "2026-10-29"}},
    ]):
        await handle_message(update, context)
    response = update.message.reply_text.call_args.args[0]
    assert "05:00 PM EDT" in response
    assert "Active fictional meeting" in response and "Active all-day fictional event" in response
    assert "Finished fictional meeting" not in response and "Future fictional meeting" not in response


@pytest.mark.asyncio
async def test_unsupported_search_question_never_falls_back_to_calendar():
    update, context = make_update("What links did I save yesterday?")
    with patch("handlers.capture.classify", return_value=Classified(type="query")), \
         patch("handlers.query.search", return_value=[]) as search, \
         patch("handlers.google.calendar.events_for_range") as read:
        await handle_message(update, context)
    search.assert_not_called()
    assert "Find <keywords>" in update.message.reply_text.call_args.args[0]
    read.assert_not_called()


@pytest.mark.asyncio
async def test_ambiguous_clock_question_waits_for_reply_before_calendar_read():
    update, context = make_update("What's on my calendar tomorrow at 5?")
    with patch("handlers.google.calendar.events_for_range", return_value=[]) as read:
        await handle_message(update, context)
        read.assert_not_called()
        assert "AM or PM" in update.message.reply_text.call_args.args[0]
        update.message.text = "5pm"
        await handle_message(update, context)
    read.assert_called_once()
    assert "05:00 PM EDT" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_event_clarification_keeps_original_date_when_midnight_passes(monkeypatch):
    original = datetime(2026, 12, 31, 23, 59, tzinfo=ZoneInfo("America/New_York"))
    monkeypatch.setattr(dates, "now_local", lambda: original)
    update, context = make_update("Fictional meeting tomorrow")
    with patch("handlers.capture.classify", return_value=Classified(type="event")):
        await handle_message(update, context)
        monkeypatch.setattr(dates, "now_local", lambda: original + timedelta(minutes=3))
        update.message.text = "5pm"
        await handle_message(update, context)
    assert recent()[0]["event_dt"] == "2027-01-01T17:00:00-05:00"


@pytest.mark.asyncio
async def test_dst_fold_is_clarified_before_add_button_is_available():
    update, context = make_update("Fictional meeting 2026-11-01 at 1:30am")
    with patch("handlers.capture.classify", return_value=Classified(type="event")):
        await handle_message(update, context)
        assert not recent() and not context.application.bot_data
        assert "ambiguous" in update.message.reply_text.call_args.args[0]
        update.message.text = "EST"
        await handle_message(update, context)
    assert recent()[0]["event_dt"] == "2026-11-01T01:30:00-05:00"
    assert "EST" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("clock, expected_start, expected_end", [
    ("2026-03-08T12:00:00-04:00", "2026-03-08T00:00:00-05:00", "2026-03-09T00:00:00-04:00"),
    ("2026-11-01T12:00:00-05:00", "2026-11-01T00:00:00-04:00", "2026-11-02T00:00:00-05:00"),
])
async def test_calendar_read_receives_dst_correct_bounds(clock, expected_start, expected_end, monkeypatch):
    monkeypatch.setattr(dates, "now_local", lambda: datetime.fromisoformat(clock))
    update, context = make_update("What's on my calendar today?")
    with patch("handlers.google.calendar.events_for_range", return_value=[]) as read:
        await handle_message(update, context)
    start, end = read.call_args.args
    assert start.isoformat() == expected_start
    assert end.isoformat() == expected_end


@pytest.mark.asyncio
@pytest.mark.parametrize("question, answer, expected", [
    ("Show calendar next week at 5pm", "2026-11-06", "2026-11-06T17:00:00-05:00"),
    ("Show calendar next week at 5pm", "Friday", "2026-11-06T17:00:00-05:00"),
    ("Show calendar 2026-11-01 at 1:30am", "EST", "2026-11-01T01:30:00-05:00"),
    ("Show calendar 2026-11-01 at 1:30am", "EDT", "2026-11-01T01:30:00-04:00"),
    ("Show calendar 2026-11-01 at 1:30am", "2026-11-01T01:30:00-05:00", "2026-11-01T01:30:00-05:00"),
])
async def test_query_clarification_preserves_supplied_components(question, answer, expected):
    update, context = make_update(question)
    captured = []
    original_resolve = dates.resolve_query

    def resolve(*args, **kwargs):
        value = original_resolve(*args, **kwargs)
        captured.append(value)
        return value

    with patch("dates.resolve_query", side_effect=resolve), \
         patch("handlers.google.calendar.events_for_range", return_value=[]) as read:
        await handle_message(update, context)
        read.assert_not_called()
        update.message.text = answer
        await handle_message(update, context)
    read.assert_called_once()
    assert captured[-1].at.isoformat() == expected
    assert not context.user_data


@pytest.mark.asyncio
@pytest.mark.parametrize("answer, offset", [("EST", "-05:00"), ("EDT", "-04:00")])
async def test_iso_event_keeps_clock_when_only_timezone_is_clarified(answer, offset):
    update, context = make_update("Fictional meeting 2026-11-01T01:30:00")
    with patch("handlers.capture.classify", return_value=Classified(type="event")), \
         patch("handlers.google.calendar.create_event") as create:
        await handle_message(update, context)
        assert "ambiguous" in update.message.reply_text.call_args.args[0]
        assert not recent() and not context.application.bot_data
        update.message.text = answer
        await handle_message(update, context)
    assert recent()[0]["event_dt"] == "2026-11-01T01:30:00" + offset
    create.assert_not_called()
    assert update.message.reply_text.call_args.kwargs["reply_markup"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["event", "query"])
@pytest.mark.parametrize("ambiguous, correction, hour", [
    ("at 5", "5pm", 17),
    ("5:00", "7pm", 19),
    ("at 5", "at 18:00", 18),
])
async def test_corrected_time_replaces_ambiguous_reply_and_preserves_date(kind, ambiguous, correction, hour):
    initial = "Fictional meeting next week" if kind == "event" else "Show calendar next week at 5"
    update, context = make_update(initial)
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Fictional meeting")) as model, \
         patch("handlers.google.calendar.create_event") as create, \
         patch("handlers.google.calendar.events_for_range", return_value=[]) as read:
        for reply in [initial, "Friday", ambiguous]:
            update.message.text = reply
            await handle_message(update, context)
            assert not recent() and not context.application.bot_data
            assert "reply_markup" not in update.message.reply_text.call_args.kwargs
            read.assert_not_called()
            create.assert_not_called()
        values = context.user_data["pending_date_clarification"]["values"]
        assert values.date == "Friday" and values.clock == ambiguous
        update.message.text = correction
        await handle_message(update, context)
        create.assert_not_called()
    assert not context.user_data
    if kind == "event":
        model.assert_called_once()
        read.assert_not_called()
        expected = f"2026-11-06T{hour:02}:00:00-05:00"
        row = recent()[0]
        assert row["event_dt"] == expected
        assert context.application.bot_data[f"pending_cal_{row['id']}"]["event_dt"] == expected
        markup = update.message.reply_text.call_args.kwargs["reply_markup"]
        assert markup.inline_keyboard[0][0].callback_data == f"cal_add:{row['id']}"
    else:
        model.assert_not_called()
        read.assert_called_once()
        start, end = read.call_args.args
        assert start.isoformat() == "2026-11-06T00:00:00-05:00"
        assert end.isoformat() == "2026-11-07T00:00:00-05:00"
        assert f"{hour - 12:02}:00 PM EST" in update.message.reply_text.call_args.args[0]
        assert not recent() and not context.application.bot_data


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["event", "query"])
async def test_date_correction_retains_clock_and_zone_from_previous_reply(kind):
    initial = "Fictional meeting next week" if kind == "event" else "Show calendar next week at 5"
    update, context = make_update(initial)
    with patch("handlers.capture.classify", return_value=Classified(type="event")), \
         patch("handlers.google.calendar.events_for_range", return_value=[]) as read, \
         patch("handlers.google.calendar.create_event") as create:
        for reply in [initial, "at 5 EST", "7pm", "Friday"]:
            update.message.text = reply
            await handle_message(update, context)
        create.assert_not_called()
    assert not context.user_data
    if kind == "event":
        assert recent()[0]["event_dt"] == "2026-11-06T19:00:00-05:00"
        assert update.message.reply_text.call_args.kwargs["reply_markup"]
    else:
        read.assert_called_once()
        assert "07:00 PM EST" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["Meeting 10/29/26 5pm", "10/29/26 5pm", "Meeting 2026-10-29 5pm"])
async def test_october_28_telegram_typo_then_explicit_date_recovers(reply, monkeypatch):
    monkeypatch.setattr(dates, "now_local", lambda: NOW.replace(day=28))
    update, context = make_update("Meeting tonmorow")
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Meeting", description="Original details")) as model, \
         patch("handlers.google.calendar.create_event") as create:
        await handle_message(update, context)
        assert not recent() and not context.application.bot_data
        # Typo support now resolves tomorrow, but a time must still be supplied.
        assert "What time" in update.message.reply_text.call_args.args[0]
        update.message.text = reply
        await handle_message(update, context)
        create.assert_not_called()
    model.assert_called_once()
    row = recent()[0]
    assert row["raw"] == "Meeting tonmorow" and row["title"] == "Meeting"
    assert row["event_dt"] == "2026-10-29T17:00:00-04:00"
    pending = context.application.bot_data[f"pending_cal_{row['id']}"]
    assert pending["description"] == "Original details"
    assert update.message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data == f"cal_add:{row['id']}"
    assert not context.user_data


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["event", "query"])
@pytest.mark.parametrize("reply", ["10/29/26", "Meeting 10/29/26", "Meeting 2026-10-29"])
async def test_date_only_correction_preserves_existing_time_and_title(kind, reply):
    initial = "Fictional meeting at 5pm" if kind == "event" else "Show calendar at 5pm"
    update, context = make_update(initial)
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Original title")), \
         patch("handlers.google.calendar.events_for_range", return_value=[]) as read, \
         patch("handlers.google.calendar.create_event") as create:
        await handle_message(update, context)
        assert "date" in update.message.reply_text.call_args.args[0].lower()
        update.message.text = reply
        await handle_message(update, context)
        create.assert_not_called()
    assert not context.user_data
    if kind == "event":
        assert recent()[0]["event_dt"] == "2026-10-29T17:00:00-04:00"
        assert recent()[0]["title"] == "Original title"
    else:
        read.assert_called_once()
        assert "2026-10-29" in update.message.reply_text.call_args.args[0]
        assert "05:00 PM EDT" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["event", "query"])
async def test_unrecognized_replies_end_clarification_without_writes(kind):
    update, context = make_update("Meeting" if kind == "event" else "Show calendar")
    with patch("handlers.capture.classify", return_value=Classified(type="event")), \
         patch("handlers.google.calendar.create_event") as create, \
         patch("handlers.google.calendar.events_for_range") as read:
        await handle_message(update, context)
        for _ in range(4):
            update.message.text = "still unsure"
            await handle_message(update, context)
        create.assert_not_called()
        read.assert_not_called()
    assert not context.user_data and not recent() and not context.application.bot_data
    response = update.message.reply_text.call_args.args[0]
    assert "clarification is closed" in response and "MM-DD-YYYY" in response


@pytest.mark.asyncio
async def test_invalid_numeric_date_can_be_replaced_by_full_iso_message():
    update, context = make_update("Meeting at 5pm")
    with patch("handlers.capture.classify", return_value=Classified(type="event")), \
         patch("handlers.google.calendar.create_event") as create:
        for reply in ["Meeting at 5pm", "Meeting 10/32/26", "Meeting 2026-10-29"]:
            update.message.text = reply
            await handle_message(update, context)
            create.assert_not_called()
            if reply == "Meeting 10/32/26":
                assert "not valid" in update.message.reply_text.call_args.args[0]
                assert not recent()
    assert recent()[0]["event_dt"] == "2026-10-29T17:00:00-04:00"
    assert not context.user_data


@pytest.mark.asyncio
async def test_reported_full_message_recovers_from_pending_date_question(monkeypatch):
    from handlers import date_clarification

    clock = NOW.replace(day=28)
    monkeypatch.setattr(dates, "now_local", lambda: clock)
    update, context = make_update("Meeting tonmorow")
    # Reproduce the pending date-question state observed before typo support.
    await date_clarification.ask(
        update, context, kind="event", text="Meeting tonmorow", now=clock,
        question="What date is the event?", result=Classified(type="event", title="Meeting"),
    )
    update.message.text = "Meeting 10/29/26 5pm"
    with patch("handlers.capture.classify") as model, \
         patch("handlers.google.calendar.create_event") as create:
        await handle_message(update, context)
    model.assert_not_called()
    create.assert_not_called()
    assert recent()[0]["event_dt"] == "2026-10-29T17:00:00-04:00"
    assert update.message.reply_text.call_args.kwargs["reply_markup"]
    assert not context.user_data


@pytest.mark.asyncio
async def test_dinner_saturday_at_noon_gets_friendly_preview_without_date_question(monkeypatch):
    monkeypatch.setattr(dates, "now_local", lambda: NOW.replace(day=28))
    update, context = make_update("Dinner Saturday at Noon")
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Dinner")), \
         patch("handlers.google.calendar.create_event") as create:
        await handle_message(update, context)
    create.assert_not_called()
    assert recent()[0]["event_dt"] == "2026-10-31T12:00:00-04:00"
    response = update.message.reply_text.call_args.args[0]
    assert "Sat Oct 31, 2026" in response and "12:00 PM EDT" in response
    assert update.message.reply_text.call_args.kwargs["parse_mode"] is None
    assert update.message.reply_text.call_args.kwargs["reply_markup"]
    assert not context.user_data


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["event", "query"])
@pytest.mark.parametrize("correction", ["10-31", "Saturday 10/31", "Dinner Saturday 10-31-2026"])
async def test_friday_date_rejected_then_saturday_correction_retains_time(kind, correction, monkeypatch):
    monkeypatch.setattr(dates, "now_local", lambda: NOW.replace(day=28))
    # The contradictory initial message must clarify even though each date on
    # its own is valid. It must not lose Saturday on a subsequent date-only reply.
    initial = "Dinner Saturday 2026-10-30 at Noon" if kind == "event" else "Show calendar Saturday 2026-10-30 at Noon"
    update, context = make_update(initial)
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Dinner", description="Original dinner details")), \
         patch("handlers.google.calendar.create_event") as create, \
         patch("handlers.google.calendar.events_for_range", return_value=[]) as read:
        for reply in [initial, "2026-10-30"]:
            update.message.text = reply
            await handle_message(update, context)
            assert "not Saturday" in update.message.reply_text.call_args.args[0]
            assert not recent() and not context.application.bot_data
            assert "reply_markup" not in update.message.reply_text.call_args.kwargs
            create.assert_not_called()
            read.assert_not_called()
        update.message.text = correction
        await handle_message(update, context)
        create.assert_not_called()
    assert not context.user_data
    if kind == "event":
        assert recent()[0]["event_dt"] == "2026-10-31T12:00:00-04:00"
        assert recent()[0]["title"] == "Dinner"
        assert context.application.bot_data[f"pending_cal_{recent()[0]['id']}"]["description"] == "Original dinner details"
        assert update.message.reply_text.call_args.kwargs["reply_markup"]
    else:
        read.assert_called_once()
        assert "12:00 PM EDT" in update.message.reply_text.call_args.args[0]


@pytest.mark.asyncio
async def test_weekday_learned_in_reply_survives_subsequent_date_correction():
    update, context = make_update("Dinner")
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Dinner")), \
         patch("handlers.google.calendar.create_event") as create:
        for reply in ["Dinner", "Saturday", "2026-10-30 at noon"]:
            update.message.text = reply
            await handle_message(update, context)
            create.assert_not_called()
        assert "not Saturday" in update.message.reply_text.call_args.args[0]
        assert not recent()
        update.message.text = "10/31"
        await handle_message(update, context)
        create.assert_not_called()
    assert recent()[0]["event_dt"] == "2026-10-31T12:00:00-04:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("correction", ["01-02-2027", "January 2 2027", "2027"])
async def test_past_inferred_year_can_be_corrected_at_year_boundary(correction, monkeypatch):
    clock = datetime(2026, 12, 31, 12, tzinfo=ZoneInfo("America/New_York"))
    monkeypatch.setattr(dates, "now_local", lambda: clock)
    update, context = make_update("Dinner January 2 at noon")
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Dinner")), \
         patch("handlers.google.calendar.create_event") as create:
        await handle_message(update, context)
        assert "Which year" in update.message.reply_text.call_args.args[0]
        assert not recent() and not context.application.bot_data
        update.message.text = correction
        await handle_message(update, context)
        create.assert_not_called()
    assert recent()[0]["event_dt"] == "2027-01-02T12:00:00-05:00"
    assert not context.user_data


@pytest.mark.asyncio
async def test_corrected_date_only_creates_event_after_explicit_add():
    from handlers.calendar_confirm import handle_callback

    update, context = make_update("Dinner Saturday 2026-10-30 at Noon")
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Dinner")), \
         patch("handlers.google.calendar.create_event", return_value={}) as create:
        await handle_message(update, context)
        create.assert_not_called()
        update.message.text = "10-31-2026"
        await handle_message(update, context)
        create.assert_not_called()
        row = recent()[0]
        callback = MagicMock()
        callback.effective_user.id = config.TELEGRAM_USER_ID
        callback.callback_query.data = f"cal_add:{row['id']}"
        callback.callback_query.answer = AsyncMock()
        callback.callback_query.edit_message_text = AsyncMock()
        await handle_callback(callback, context)
        create.assert_called_once_with(summary="Dinner", start_dt="2026-10-31T12:00:00-04:00", description=None)


@pytest.mark.asyncio
async def test_next_saturday_at_year_end_uses_following_week(monkeypatch):
    clock = datetime(2026, 12, 31, 12, tzinfo=ZoneInfo("America/New_York"))
    monkeypatch.setattr(dates, "now_local", lambda: clock)
    update, context = make_update("Dinner next Saturday at noon")
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Dinner")), \
         patch("handlers.google.calendar.create_event") as create:
        await handle_message(update, context)
    create.assert_not_called()
    assert recent()[0]["event_dt"] == "2027-01-09T12:00:00-05:00"


@pytest.mark.asyncio
@pytest.mark.parametrize("word", ["tonight", "today"])
async def test_same_day_capture_asks_for_time_then_previews_without_creating(word):
    update, context = make_update(f"Dinner {word}")
    with patch("handlers.capture.classify", return_value=Classified(type="event", title="Dinner")) as model, \
         patch("handlers.google.calendar.create_event") as create:
        await handle_message(update, context)
        assert "What time" in update.message.reply_text.call_args.args[0]
        assert not recent() and not context.application.bot_data
        update.message.text = "7pm"
        await handle_message(update, context)
        create.assert_not_called()
    model.assert_called_once()
    assert recent()[0]["event_dt"] == "2026-10-27T19:00:00-04:00"
    assert update.message.reply_text.call_args.kwargs["reply_markup"]
    assert not context.user_data


@pytest.mark.asyncio
async def test_tonight_query_bypasses_classifier_and_reads_current_local_day():
    update, context = make_update("What's on my calendar tonight?")
    with patch("handlers.capture.classify") as model, \
         patch("handlers.google.calendar.events_for_range", return_value=[]) as read:
        await handle_message(update, context)
    model.assert_not_called()
    start, end = read.call_args.args
    assert start.isoformat() == "2026-10-27T00:00:00-04:00"
    assert end.isoformat() == "2026-10-28T00:00:00-04:00"
