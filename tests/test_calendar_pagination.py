from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

import dates
from handlers.capture import handle_message
from handlers.google import calendar as cal


@pytest.mark.asyncio
async def test_timed_query_finds_event_on_page_two_with_same_bounds(monkeypatch):
    monkeypatch.setattr(dates, "now_local", lambda: datetime(2026, 10, 27, 12, tzinfo=ZoneInfo("America/New_York")))
    first, second = MagicMock(), MagicMock()
    first.execute.return_value = {
        "items": [{"summary": "Finished fictional event", "start": {"dateTime": "2026-10-28T15:00:00-04:00"},
                   "end": {"dateTime": "2026-10-28T16:00:00-04:00"}}],
        "nextPageToken": "fictional-page-two",
    }
    second.execute.return_value = {
        "items": [{"summary": "Relevant fictional event", "start": {"dateTime": "2026-10-28T17:00:00-04:00"},
                   "end": {"dateTime": "2026-10-28T18:00:00-04:00"}}],
    }
    update, context = MagicMock(), MagicMock()
    update.message.text = "What's on my calendar tomorrow at 5pm?"
    update.message.reply_text = AsyncMock()
    context.user_data = {}
    context.application.bot_data = {}
    with patch.object(cal, "_service") as service:
        listing = service.return_value.events.return_value.list
        listing.side_effect = [first, second]
        await handle_message(update, context)
    reply = update.message.reply_text.call_args.args[0]
    assert "Relevant fictional event" in reply
    assert "Finished fictional event" not in reply
    assert listing.call_count == 2
    initial, following = (call.kwargs for call in listing.call_args_list)
    assert following == {**initial, "pageToken": "fictional-page-two"}
    assert initial["timeMin"] == "2026-10-28T00:00:00-04:00"
    assert initial["timeMax"] == "2026-10-29T00:00:00-04:00"
    service.assert_called_once()


def test_repeated_page_marker_fails_instead_of_looping_or_returning_partial_data():
    start, end = dates.resolve_query("2026-11-12").bounds()
    with patch.object(cal, "_service") as service:
        service.return_value.events.return_value.list.return_value.execute.return_value = {
            "items": [], "nextPageToken": "fictional-repeated-page",
        }
        with pytest.raises(RuntimeError):
            cal.events_for_range(start, end)
