from unittest.mock import MagicMock, patch

import pytest

import config


def _make_timed_event(summary: str, dt_str: str) -> dict:
    return {"summary": summary, "start": {"dateTime": dt_str}}


def _make_allday_event(summary: str, date_str: str) -> dict:
    return {"summary": summary, "start": {"date": date_str}}


def test_format_timed_event_et():
    from handlers.google.calendar import format_event

    ev = _make_timed_event("Team standup", "2026-10-23T09:00:00-04:00")
    result = format_event(ev)
    assert "Team standup" in result
    assert "9:00 AM" in result


def test_format_allday_event():
    from handlers.google.calendar import format_event

    ev = _make_allday_event("Company holiday", "2026-10-26")
    result = format_event(ev)
    assert "Company holiday" in result
    assert "all day" in result


def test_format_event_no_title():
    from handlers.google.calendar import format_event

    ev = {"summary": "", "start": {"dateTime": "2026-10-23T10:00:00-04:00"}}
    ev["summary"] = ""
    result = format_event(ev)
    assert "(no title)" in result


def test_today_events_empty_calendar():
    from handlers.google import calendar as cal

    with patch("handlers.google.calendar._service") as mock_svc:
        mock_svc.return_value.events.return_value.list.return_value.execute.return_value = {
            "items": []
        }
        result = cal.today_events()

    assert result == []


def test_today_events_returns_formatted_strings():
    from handlers.google import calendar as cal

    events = [
        _make_timed_event("Morning standup", "2026-10-23T09:00:00-04:00"),
        _make_allday_event("All-hands", "2026-10-23"),
    ]
    with patch("handlers.google.calendar._service") as mock_svc:
        mock_svc.return_value.events.return_value.list.return_value.execute.return_value = {
            "items": events
        }
        result = cal.today_events()

    assert len(result) == 2
    assert "Morning standup" in result[0]
    assert "All-hands" in result[1]
    assert "all day" in result[1]


def test_week_events_queries_7_day_range():
    from handlers.google import calendar as cal

    with patch("handlers.google.calendar._service") as mock_svc:
        exec_mock = mock_svc.return_value.events.return_value.list.return_value.execute
        exec_mock.return_value = {"items": []}
        cal.week_events()

    list_call_kwargs = mock_svc.return_value.events.return_value.list.call_args.kwargs
    from datetime import datetime
    from zoneinfo import ZoneInfo

    time_min = datetime.fromisoformat(list_call_kwargs["timeMin"])
    time_max = datetime.fromisoformat(list_call_kwargs["timeMax"])
    delta = time_max - time_min
    assert delta.days == 7


def test_google_service_uses_bounded_authorized_transport():
    from handlers.google import calendar as cal

    with patch("handlers.google.calendar.get_credentials") as credentials, \
         patch("handlers.google.calendar.httplib2.Http") as http, \
         patch("handlers.google.calendar.AuthorizedHttp") as authorized, \
         patch("handlers.google.calendar.build") as build:
        cal._service()
    http.assert_called_once_with(timeout=30)
    authorized.assert_called_once_with(credentials.return_value, http=http.return_value)
    assert build.call_args.kwargs["http"] is authorized.return_value
    assert "credentials" not in build.call_args.kwargs
