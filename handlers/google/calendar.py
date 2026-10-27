from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from google_auth_httplib2 import AuthorizedHttp
import httplib2

import config
import dates
from handlers.google.auth import HTTP_TIMEOUT_SECONDS, get_credentials


def _service():
    credentials = get_credentials()
    transport = AuthorizedHttp(credentials, http=httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS))
    return build("calendar", "v3", http=transport, cache_discovery=False)


def events_for_range(start: datetime, end: datetime) -> list[dict]:
    tz = ZoneInfo(config.TIMEZONE)
    api = _service().events()
    params = {
        "calendarId": "primary", "timeMin": start.astimezone(tz).isoformat(),
        "timeMax": end.astimezone(tz).isoformat(), "singleEvents": True,
        "orderBy": "startTime",
    }
    events, seen = [], set()
    while True:
        result = api.list(**params).execute(num_retries=0)
        events.extend(result.get("items", []))
        marker = result.get("nextPageToken")
        if not marker:
            return events
        if not isinstance(marker, str) or marker in seen:
            raise RuntimeError("Google Calendar returned invalid pagination metadata.")
        seen.add(marker)
        params["pageToken"] = marker


def occurs_at(event: dict, instant: datetime) -> bool:
    """Calendar intervals include their start and exclude their end."""
    if "date" in event["start"]:
        local_day = instant.astimezone(ZoneInfo(config.TIMEZONE)).date()
        return date.fromisoformat(event["start"]["date"]) <= local_day < date.fromisoformat(event["end"]["date"])
    start = datetime.fromisoformat(event["start"]["dateTime"])
    end = datetime.fromisoformat(event["end"]["dateTime"])
    return start <= instant < end


def _fmt_date(dt: datetime) -> str:
    return f"{dt.strftime('%a %b')} {dt.day}, {dt.year} ({dt:%Y-%m-%d})"


def _fmt_time(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.strftime('%M')} {ampm}"


def format_event(ev: dict) -> str:
    summary = ev.get("summary") or "(no title)"
    start_raw = ev["start"].get("dateTime") or ev["start"].get("date", "")

    if "T" in start_raw:
        tz = ZoneInfo(config.TIMEZONE)
        dt = datetime.fromisoformat(start_raw).astimezone(tz)
        return f"• {summary} — {_fmt_date(dt)} at {_fmt_time(dt)} {dt:%Z} ({config.TIMEZONE})"

    try:
        d = datetime.strptime(start_raw, "%Y-%m-%d")
        return f"• {summary} — {_fmt_date(d)} (all day)"
    except ValueError:
        return f"• {summary} (all day)"


def format_iso_dt(dt_str: str) -> str:
    """Format an ISO 8601 date/datetime string for human display (ET)."""
    tz = ZoneInfo(config.TIMEZONE)
    if "T" in dt_str:
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        dt = dt.astimezone(tz)
        end = dates.event_end(dt)
        return (
            f"{_fmt_date(dt)} · {_fmt_time(dt)} {dt:%Z} → "
            f"{_fmt_date(end)} {_fmt_time(end)} {end:%Z} ({config.TIMEZONE}; one hour)"
        )
    try:
        d = datetime.strptime(dt_str, "%Y-%m-%d")
        return f"{_fmt_date(d)} (all day; {config.TIMEZONE})"
    except ValueError:
        return dt_str


def create_event(
    summary: str,
    start_dt: str,
    end_dt: str | None = None,
    description: str | None = None,
) -> dict:
    """Insert an event on the primary calendar. Returns the created event resource."""
    tz = ZoneInfo(config.TIMEZONE)

    if "T" in start_dt:
        start = datetime.fromisoformat(start_dt)
        if start.tzinfo is None:
            start = dates.localize(start)
        start = start.astimezone(tz)

        if end_dt and "T" in end_dt:
            end = datetime.fromisoformat(end_dt)
            if end.tzinfo is None:
                end = dates.localize(end)
            end = end.astimezone(tz)
        else:
            end = dates.event_end(start)

        body: dict = {
            "summary": summary,
            "start": {"dateTime": start.isoformat(), "timeZone": config.TIMEZONE},
            "end": {"dateTime": end.isoformat(), "timeZone": config.TIMEZONE},
        }
    else:
        start_day = date.fromisoformat(start_dt)
        # Google Calendar's all-day end date is exclusive.
        end_day = date.fromisoformat(end_dt) if end_dt else start_day + timedelta(days=1)
        if end_day <= start_day:
            raise ValueError("All-day event end must be after its start date.")
        body = {
            "summary": summary,
            "start": {"date": start_day.isoformat()},
            "end": {"date": end_day.isoformat()},
        }

    if description:
        body["description"] = description

    # Never add application-level retries to a potentially successful insertion.
    return _service().events().insert(calendarId="primary", body=body).execute(num_retries=0)


def today_events() -> list[str]:
    tz = ZoneInfo(config.TIMEZONE)
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return [format_event(e) for e in events_for_range(start, end)]


def week_events() -> list[str]:
    tz = ZoneInfo(config.TIMEZONE)
    now = datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return [format_event(e) for e in events_for_range(start, end)]
