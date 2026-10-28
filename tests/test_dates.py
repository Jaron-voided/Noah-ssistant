from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

import config
import dates


ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 27, 12, 15, tzinfo=ET)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(config, "TIMEZONE", "America/New_York")
    monkeypatch.setattr(dates, "now_local", lambda: NOW)


@pytest.mark.parametrize("message, expected", [
    ("Meeting tomorrow at 5pm", "2026-10-28T17:00:00-04:00"),
    ("Meeting this Friday at 17:00", "2026-10-30T17:00:00-04:00"),
    ("Meeting day after tomorrow at noon", "2026-10-29T12:00:00-04:00"),
    ("All-day workshop tomorrow", "2026-10-28"),
    ("All-day workshop this Friday", "2026-10-30"),
    ("Meeting 2026-11-12 at 5pm", "2026-11-12T17:00:00-05:00"),
    ("Meeting November 12th 2026 at 5pm", "2026-11-12T17:00:00-05:00"),
    ("Meeting 2026-11-12T10:00", "2026-11-12T10:00:00-05:00"),
    ("Meeting Friday next week at 5pm", "2026-11-06T17:00:00-05:00"),
    ("Meeting Friday November 6 2026 at 5pm", "2026-11-06T17:00:00-05:00"),
])
def test_event_dates_use_fixed_local_clock(message, expected):
    assert dates.resolve_event(message) == expected


@pytest.mark.parametrize("message", [
    "Meeting tomorrow at 5", "Meeting this Friday", "Meeting next week at 5pm",
    "Meeting April 3rd at 10am",
    "Meeting tomorrow at 5pm or 6pm", "Meeting tomorrow or 2026-12-01 at 5pm",
    "Meeting tomorrow evening", "Meeting tomorrow at 5pm PST",
    "All-day meeting tomorrow at 5pm", "Meeting today at 10am",
    "Meeting 2026-02-30 at 5pm", "Meeting this Monday at 5pm",
    "Meeting tomorrow next month at 5pm", "Meeting tomorrow at 25:00",
    "Meeting tomorrow at 5pm America/Los_Angeles", "Meeting Thursday November 6 2026 at 5pm",
    "Meeting 2026-11-01 at 1:30am EDT or EST", "Meeting 2026-11-01T01:30:00-04:00 EST",
])
def test_ambiguous_or_invalid_events_require_clarification(message):
    with pytest.raises(dates.ClarificationNeeded):
        dates.resolve_event(message)


@pytest.mark.parametrize("message, answer, expected", [
    ("Meeting tomorrow at 5", "5pm", "2026-10-28T17:00:00-04:00"),
    ("Meeting tomorrow", "all day", "2026-10-28"),
    ("Meeting next week", "Friday\n5pm", "2026-11-06T17:00:00-05:00"),
    ("Meeting next Friday at 5pm", "2026-11-06", "2026-11-06T17:00:00-05:00"),
])
def test_event_clarification_replaces_missing_component(message, answer, expected):
    assert dates.resolve_event(message, answer=answer) == expected


@pytest.mark.parametrize("clock, message, expected", [
    ("2026-12-31T23:58:00-05:00", "Meeting tomorrow at 5pm", "2027-01-01T17:00:00-05:00"),
    ("2027-01-01T02:00:00+00:00", "Meeting tomorrow at 5pm", "2027-01-01T17:00:00-05:00"),
    ("2028-02-28T12:00:00-05:00", "All-day meeting tomorrow", "2028-02-29"),
    ("2026-03-07T12:00:00-05:00", "Meeting tomorrow at 5pm", "2026-03-08T17:00:00-04:00"),
    ("2026-10-31T12:00:00-04:00", "Meeting tomorrow at 5pm", "2026-11-01T17:00:00-05:00"),
])
def test_event_year_leap_and_dst_boundaries(clock, message, expected):
    assert dates.resolve_event(message, datetime.fromisoformat(clock)) == expected


@pytest.mark.parametrize("message", [
    "Meeting 2026-03-08 at 2:30am", "Meeting 2026-11-01 at 1:30am",
    "Meeting 2026-03-08T02:30:00", "Meeting 2026-11-01T01:30:00",
])
def test_dst_missing_and_repeated_times_are_not_guessed(message):
    with pytest.raises(dates.ClarificationNeeded):
        dates.resolve_event(message)


@pytest.mark.parametrize("message, expected", [
    ("Meeting 2026-11-01 at 1:30am EDT", "2026-11-01T01:30:00-04:00"),
    ("Meeting 2026-11-01 at 1:30am EST", "2026-11-01T01:30:00-05:00"),
    ("Meeting 2026-11-01T01:30:00-04:00", "2026-11-01T01:30:00-04:00"),
    ("Meeting 2026-11-01T01:30:00-05:00", "2026-11-01T01:30:00-05:00"),
])
def test_explicit_dst_disambiguation_is_preserved(message, expected):
    assert dates.resolve_event(message) == expected


@pytest.mark.parametrize("message, start, end", [
    ("What is on my calendar tomorrow?", "2026-10-28", "2026-10-29"),
    ("What is on my calendar this Friday?", "2026-10-30", "2026-10-31"),
    ("Show calendar next week", "2026-11-02", "2026-11-09"),
    ("Show calendar this week", "2026-10-26", "2026-11-02"),
    ("Show calendar next 7 days", "2026-10-27", "2026-11-03"),
    ("Show calendar 2026-12-31", "2026-12-31", "2027-01-01"),
])
def test_calendar_queries_resolve_date_ranges(message, start, end):
    span = dates.resolve_query(message)
    assert span.start.isoformat() == start
    assert span.end.isoformat() == end


@pytest.mark.parametrize("clock, start, end", [
    ("2026-12-27T12:00:00-05:00", "2026-12-28", "2027-01-04"),
    ("2026-12-28T12:00:00-05:00", "2027-01-04", "2027-01-11"),
    ("2026-12-31T12:00:00-05:00", "2027-01-04", "2027-01-11"),
])
def test_next_week_crosses_sunday_monday_and_year_boundaries(clock, start, end):
    span = dates.resolve_query("next week", datetime.fromisoformat(clock))
    assert span.start.isoformat() == start
    assert span.end.isoformat() == end


@pytest.mark.parametrize("clock, expected_hours", [
    ("2026-03-08T12:00:00-04:00", 23),
    ("2026-11-01T12:00:00-05:00", 25),
])
def test_dst_day_bounds_cover_the_whole_local_day(clock, expected_hours):
    span = dates.resolve_query("today", datetime.fromisoformat(clock))
    start, end = span.bounds()
    elapsed = end.astimezone(timezone.utc) - start.astimezone(timezone.utc)
    assert elapsed.total_seconds() / 3600 == expected_hours
    assert start.hour == end.hour == 0


@pytest.mark.parametrize("clock, expected_hours", [
    ("2026-03-08T12:00:00-04:00", 167),
    ("2026-11-01T12:00:00-05:00", 169),
])
def test_dst_week_bounds_are_local_mondays_not_168_elapsed_hours(clock, expected_hours):
    span = dates.resolve_query("this week", datetime.fromisoformat(clock))
    start, end = span.bounds()
    assert start.weekday() == end.weekday() == 0
    elapsed = end.astimezone(timezone.utc) - start.astimezone(timezone.utc)
    assert elapsed.total_seconds() / 3600 == expected_hours


@pytest.mark.parametrize("message", ["What's on my calendar?", "Show calendar next month"])
def test_vague_query_does_not_default_to_today(message):
    with pytest.raises(dates.ClarificationNeeded):
        dates.resolve_query(message)


@pytest.mark.parametrize("message, expected", [
    ("What is on my calendar tomorrow at 5pm?", "2026-10-28T17:00:00-04:00"),
    ("What is on my calendar this Friday at 17:00?", "2026-10-30T17:00:00-04:00"),
    ("Show calendar 2026-11-01 at 1:30am EST", "2026-11-01T01:30:00-05:00"),
    ("Show calendar 2026-11-01T01:30:00-04:00", "2026-11-01T01:30:00-04:00"),
])
def test_calendar_questions_at_an_instant(message, expected):
    span = dates.resolve_query(message)
    assert span.at.isoformat() == expected


@pytest.mark.parametrize("message", [
    "What is on my calendar tomorrow at 5?", "Show calendar next week at 5pm",
    "Show calendar 2026-03-08 at 2:30am", "Show calendar 2026-11-01 at 1:30am",
    "Show calendar tomorrow at 5pm America/Los_Angeles",
])
def test_ambiguous_timed_calendar_questions_require_clarification(message):
    with pytest.raises(dates.ClarificationNeeded):
        dates.resolve_query(message)


def test_date_reply_preserves_an_existing_timezone_abbreviation():
    span = dates.resolve_query("Show calendar next week at 5pm EST", answer="2026-11-06")
    assert span.at.isoformat() == "2026-11-06T17:00:00-05:00"


@pytest.mark.parametrize("resolver", [dates.resolve_event, dates.resolve_query])
def test_date_reply_preserves_an_explicit_iso_offset(resolver):
    result = resolver("Meeting 2026-11-01T01:30:00-04:00 or 2026-11-02", answer="2026-11-01")
    value = result.at.isoformat() if isinstance(result, dates.DateSpan) else result
    assert value == "2026-11-01T01:30:00-04:00"


@pytest.mark.parametrize("resolver", [dates.resolve_event, dates.resolve_query])
@pytest.mark.parametrize("replies, expected", [
    (["2026-11-01T01:30:15-04:00", "2026-11-02"], "2026-11-02T01:30:15-04:00"),
    (["2026-11-01T01:30:00-04:00", "7pm"], "2026-11-01T18:00:00-05:00"),
    (["2026-11-01T10:30:00", "2026-11-02"], "2026-11-02T10:30:00-05:00"),
    (["Friday at 5", "7pm"], "2026-11-06T19:00:00-05:00"),
    (["Friday at 5 EST", "all day"], "2026-11-06"),
])
def test_structured_replies_preserve_other_components(resolver, replies, expected):
    original = "Meeting next week"
    values = dates.ClarificationValues()
    for reply in replies:
        values = values.replace_from(reply)
    result = resolver(original, NOW, answer=values.answer(original, NOW))
    value = (result.at.isoformat() if result.at else result.start.isoformat()) if isinstance(result, dates.DateSpan) else result
    # Offset-bearing ISO input denotes an instant; the result is displayed locally.
    if "T" in expected:
        expected = datetime.fromisoformat(expected).astimezone(ET).isoformat()
    assert value == expected


@pytest.mark.parametrize("reply", [
    "2026-11-01T01:30:00-04:00 EST",
    "2026-11-01T01:30:00-04:00 or 7pm",
])
@pytest.mark.parametrize("resolver", [dates.resolve_event, dates.resolve_query])
def test_structured_reply_does_not_discard_conflicting_iso_components(reply, resolver):
    values = dates.ClarificationValues().replace_from(reply)
    with pytest.raises(dates.ClarificationNeeded):
        resolver("Meeting next week", NOW, answer=values.answer("Meeting next week", NOW))


@pytest.mark.parametrize("spelling", ["tonmorow", "tomorow", "tommorow", "tommorrow", "TONMOROW"])
def test_common_tomorrow_typos_use_original_local_clock(spelling):
    assert dates.has_date_language(spelling)
    assert dates.resolve_event(f"Meeting {spelling} at 5pm") == "2026-10-28T17:00:00-04:00"
    assert dates.resolve_query(f"Show calendar {spelling}").start.isoformat() == "2026-10-28"


@pytest.mark.parametrize("numeric", ["10/29/26", "10/29/2026", "29/10/26"])
@pytest.mark.parametrize("resolver", [dates.resolve_event, dates.resolve_query])
def test_unambiguous_numeric_dates_in_full_messages(numeric, resolver):
    result = resolver(f"Meeting {numeric} 5pm")
    value = result.at.isoformat() if isinstance(result, dates.DateSpan) else result
    assert value == "2026-10-29T17:00:00-04:00"


@pytest.mark.parametrize("numeric", ["02/30/26", "13/32/26", "10/29/2026 tomorrow"])
def test_numeric_dates_do_not_guess_ambiguous_missing_or_invalid_values(numeric):
    with pytest.raises(dates.ClarificationNeeded):
        dates.resolve_event(f"Meeting {numeric} 5pm")


@pytest.mark.parametrize("phrase, expected", [
    ("Saturday", "2026-10-31T12:00:00-04:00"),
    ("next Saturday", "2026-11-07T12:00:00-05:00"),
    ("Monday", "2026-11-02T12:00:00-05:00"),
    ("Friday", "2026-10-30T12:00:00-04:00"),
])
@pytest.mark.parametrize("resolver", [dates.resolve_event, dates.resolve_query])
def test_natural_weekdays(phrase, expected, resolver):
    result = resolver(f"Dinner {phrase} at Noon", NOW.replace(day=28))
    assert (result.at.isoformat() if isinstance(result, dates.DateSpan) else result) == expected


@pytest.mark.parametrize("clock, phrase, expected", [
    ("2026-12-31T12:00:00-05:00", "Saturday", "2027-01-02T12:00:00-05:00"),
    ("2026-12-31T12:00:00-05:00", "next Saturday", "2027-01-09T12:00:00-05:00"),
    ("2026-10-31T10:00:00-04:00", "Saturday", "2026-10-31T12:00:00-04:00"),
    ("2026-10-31T13:00:00-04:00", "Saturday", "2026-11-07T12:00:00-05:00"),
    ("2026-11-01T10:00:00-05:00", "next Saturday", "2026-11-07T12:00:00-05:00"),
    ("2027-01-04T10:00:00-05:00", "next Saturday", "2027-01-16T12:00:00-05:00"),
])
def test_weekday_boundaries_and_same_day(clock, phrase, expected):
    assert dates.resolve_event(f"Dinner {phrase} at noon", datetime.fromisoformat(clock)) == expected


@pytest.mark.parametrize("phrase", ["11-12", "11/12", "November 12", "Nov 12th", "11-12-2026", "11/12/2026"])
@pytest.mark.parametrize("resolver", [dates.resolve_event, dates.resolve_query])
def test_month_day_formats_default_current_year(phrase, resolver):
    result = resolver(f"Dinner {phrase} at noon")
    assert (result.at.isoformat() if isinstance(result, dates.DateSpan) else result) == "2026-11-12T12:00:00-05:00"


@pytest.mark.parametrize("phrase", ["01-02", "01/02", "January 2", "10-27"])
def test_inferred_year_in_past_requires_clarification(phrase):
    with pytest.raises(dates.ClarificationNeeded, match="Which year"):
        dates.resolve_event(f"Dinner {phrase} at noon")


@pytest.mark.parametrize("clock, phrase, expected", [
    ("2026-12-31T12:00:00-05:00", "January 2 2027", "2027-01-02T12:00:00-05:00"),
    ("2027-01-01T02:00:00+00:00", "12/31 at 11pm", "2026-12-31T23:00:00-05:00"),
    ("2027-01-01T12:00:00-05:00", "12-31-2026", "2026-12-31T12:00:00-05:00"),
    ("2028-01-01T12:00:00-05:00", "February 29", "2028-02-29T12:00:00-05:00"),
])
def test_explicit_year_and_local_year_are_preserved(clock, phrase, expected):
    suffix = "" if "pm" in phrase else " at noon"
    assert dates.resolve_event(f"Dinner {phrase}{suffix}", datetime.fromisoformat(clock)) == expected


@pytest.mark.parametrize("resolver", [dates.resolve_event, dates.resolve_query])
@pytest.mark.parametrize("correction", ["2026-10-30", "10-30-2026", "10/30", "2026-10-30T12:00:00-04:00"])
def test_date_only_correction_cannot_discard_original_saturday(resolver, correction):
    with pytest.raises(dates.ClarificationNeeded, match="not Saturday"):
        resolver("Dinner Saturday at noon", NOW.replace(day=28), answer=correction)


@pytest.mark.parametrize("resolver", [dates.resolve_event, dates.resolve_query])
def test_explicit_weekday_correction_can_replace_original_weekday(resolver):
    result = resolver("Dinner Saturday at noon", NOW, answer="Friday 10-30-2026")
    assert (result.at.isoformat() if isinstance(result, dates.DateSpan) else result) == "2026-10-30T12:00:00-04:00"


@pytest.mark.parametrize("resolver", [dates.resolve_event, dates.resolve_query])
def test_structured_date_replies_keep_weekday_and_explicit_year(resolver):
    values = dates.ClarificationValues().replace_from("Saturday November 7 2026")
    values = values.replace_from("11-14")
    answer = values.answer("Dinner at noon", NOW)
    result = resolver("Dinner at noon", NOW, answer=answer)
    assert (result.at.isoformat() if isinstance(result, dates.DateSpan) else result) == "2026-11-14T12:00:00-05:00"
    values = values.replace_from("11-13")
    with pytest.raises(dates.ClarificationNeeded, match="not Saturday"):
        resolver("Dinner at noon", NOW, answer=values.answer("Dinner at noon", NOW))


def test_correction_without_year_keeps_original_explicit_year():
    assert dates.resolve_event("Dinner 11-12-2027 at noon", NOW, answer="11-13") == "2027-11-13T12:00:00-05:00"
    values = dates.ClarificationValues().replace_from("11-12-2027").replace_from("11/13")
    assert dates.resolve_event("Dinner at noon", NOW, answer=values.answer("Dinner at noon", NOW)) == "2027-11-13T12:00:00-05:00"


@pytest.mark.parametrize("word", ["tonight", "today", "TONIGHT"])
@pytest.mark.parametrize("resolver", [dates.resolve_event, dates.resolve_query])
def test_today_and_tonight_at_explicit_time_use_local_date(word, resolver):
    result = resolver(f"Dinner {word} at 7pm", NOW)
    assert (result.at.isoformat() if isinstance(result, dates.DateSpan) else result) == "2026-10-27T19:00:00-04:00"


@pytest.mark.parametrize("text", ["Dinner tonight", "Dinner tonight at 7"])
def test_tonight_does_not_invent_time_or_am_pm(text):
    with pytest.raises(dates.ClarificationNeeded, match="What time|AM or PM"):
        dates.resolve_event(text, NOW)


@pytest.mark.parametrize("word", ["tonight", "today"])
@pytest.mark.parametrize("in_reply", [False, True])
def test_same_day_past_times_require_clarification_in_original_and_reply(word, in_reply):
    text, answer = ("Dinner at 10am", word) if in_reply else (f"Dinner {word} at 10am", "")
    with pytest.raises(dates.ClarificationNeeded, match="already passed"):
        dates.resolve_event(text, NOW, answer=answer)


def test_tonight_at_year_boundary_uses_local_date_not_utc_date():
    clock = datetime.fromisoformat("2027-01-01T02:00:00+00:00")
    assert dates.resolve_event("Dinner tonight at 11pm", clock) == "2026-12-31T23:00:00-05:00"
    assert dates.resolve_query("Show calendar tonight", clock).start.isoformat() == "2026-12-31"
