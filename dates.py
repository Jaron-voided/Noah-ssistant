"""Resolve supported calendar language without trusting model-generated dates."""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo

import config


class ClarificationNeeded(ValueError):
    """A user must supply a missing or ambiguous date/time component."""


def now_local() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def local_reference(now: datetime | None = None) -> datetime:
    value = now if now is not None else now_local()
    if value.tzinfo is None:
        raise ValueError("The reference clock must include a timezone.")
    return value.astimezone(ZoneInfo(config.TIMEZONE))


def localize(naive: datetime, abbreviation: str | None = None) -> datetime:
    """Reject missing/repeated wall times unless the user disambiguates them."""
    tz = ZoneInfo(config.TIMEZONE)
    choices = {}
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=tz, fold=fold)
        roundtrip = candidate.astimezone(timezone.utc).astimezone(tz)
        if roundtrip.replace(tzinfo=None) == naive:
            choices[candidate.utcoffset()] = candidate
    if not choices:
        raise ClarificationNeeded(
            f"That local time does not exist during the clock change in {config.TIMEZONE}. "
            "What other time should I use?"
        )
    if abbreviation:
        choices = {offset: value for offset, value in choices.items()
                   if value.tzname() == abbreviation}
    if len(choices) != 1:
        raise ClarificationNeeded(
            f"That time is ambiguous in {config.TIMEZONE}. "
            "Please give an ISO date/time with a UTC offset, or specify EDT/EST."
        )
    return next(iter(choices.values()))


@dataclass(frozen=True)
class DateSpan:
    start: date
    end: date  # exclusive
    at: datetime | None = None  # optional point-in-time filter within the day
    inferred_year: bool = field(default=False, compare=False)

    def bounds(self) -> tuple[datetime, datetime]:
        return (localize(datetime.combine(self.start, time())),
                localize(datetime.combine(self.end, time())))


@dataclass(frozen=True)
class ClarificationValues:
    """Latest supplied value for each component, separate from the original input.

    Keep ambiguous values too: they must still prompt, but a later correction
    replaces that component rather than being appended to it.
    """
    date: str = ""
    clock: str = ""
    zone: str = ""
    offset: str = ""
    iso_clock: bool = False
    weekday: str = ""
    year: int | None = None

    def replace_from(self, reply: str) -> "ClarificationValues":
        reply = _normalize_relative(reply)
        day, clock, zone, offset = self.date, self.clock, self.zone, self.offset
        iso_clock = self.iso_clock
        stamps = list(_ISO_STAMP.finditer(reply.lower()))
        if len(stamps) == 1:
            stamp = stamps[0]
            # Retain the wall clock and offset independently so date/time replies
            # can correct either without discarding the other.
            stamp_text = stamp.group().upper()
            stamp_day, stamp_clock = re.split(r"[T ]", stamp_text, maxsplit=1)
            suffix = re.search(r"(Z|[+-]\d{2}:\d{2})$", stamp_clock)
            offset = suffix.group() if suffix else ""
            clock = stamp_clock[:suffix.start()] if suffix else stamp_clock
            iso_clock = True
            day = reply[:stamp.start()] + stamp_day + reply[stamp.end():]
            extra_clocks = list(_TIME.finditer((reply[:stamp.start()] + reply[stamp.end():]).lower()))
            if extra_clocks:
                clock = stamp_text + " " + " ".join(m.group() for m in extra_clocks)
                iso_clock = False
            day = _strip_times(day)
            zone = ""
        else:
            clocks = list(_time_matches(reply))
            modes = re.findall(r"\ball[ -]day\b|\bwhole day\b|\bnoon\b|\bmidnight\b", reply, re.I)
            if clocks or modes:
                clock = " ".join([m.group() for m in clocks] + modes)
                iso_clock = False
            date_reply = re.sub(r"\ball[ -]day\b|\bwhole day\b|\bnoon\b|\bmidnight\b", "", _strip_times(reply), flags=re.I)
            if has_date_language(date_reply) or _MONTH_DAY.search(date_reply.lower()):
                day = date_reply
        zone_pattern = r"\b(?:EST|EDT|PST|PDT|CST|CDT|MST|MDT|UTC|GMT|BST|CET|CEST|IST|JST|AEST|AEDT)\b|\b[A-Za-z_]+/[A-Za-z_]+\b"
        zones = re.findall(zone_pattern, reply, re.I)
        if zones:
            zone = " ".join(zones)
            if len(stamps) != 1:
                offset = ""
        # Zone words belong to their own component, including invalid zones that
        # must continue asking for clarification until explicitly corrected.
        day = re.sub(zone_pattern, "", day, flags=re.I)
        weekdays = list(_WEEKDAY.finditer(reply.lower()))
        weekday = " ".join(m.group() for m in weekdays) if weekdays else self.weekday
        year_reply = re.fullmatch(r"(?:in\s+)?(\d{4})", reply.strip(), re.I)
        year = int(year_reply[1]) if year_reply else (_explicit_year(reply) or self.year)
        return ClarificationValues(day, clock, zone, offset, iso_clock, weekday, year)

    def answer(self, original: str, now: datetime) -> str:
        date_text = self.date or (_strip_times(original) if self.year else "")
        day = _supply_year(date_text, self.year or _explicit_year(original))
        if self.weekday and not _WEEKDAY.search(day.lower()):
            day = f"{self.weekday} {day}"
        if self.offset or self.iso_clock:
            # Validate each component before assembling an offset-bearing stamp.
            week = re.search(r"\b(this|next) week\b", original, re.I)
            context = _span(week.group(), now) if week else None
            span = _span(day, now, week_context=context) or _span(original, now)
            try:
                clock = time.fromisoformat(self.clock) if self.iso_clock else _clock(self.clock)
            except ValueError:
                raise ClarificationNeeded("Please give a valid ISO date/time.") from None
            if span and (span.end - span.start).days == 1 and clock is not None:
                _check_weekday(original, day, span)
                return f"{span.start.isoformat()}T{clock.isoformat()}{self.offset} {self.zone}".strip()
        return "\n".join(value for value in (day, self.clock, self.zone) if value)


_WEEKDAYS = "monday tuesday wednesday thursday friday saturday sunday".split()
_MONTHS = "january february march april may june july august september october november december".split()
_ISO_DAY = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
_NUMERIC_DAY = re.compile(r"(?<![\d/:Tt-])(?P<first>\d{1,2})(?P<sep>[-/])(?P<second>\d{1,2})(?:(?P=sep)(?P<year>\d{4}|\d{2}))?(?![\d/:-])")
_WEEKDAY = re.compile(r"\b(?:(this|next)\s+)?(" + "|".join(_WEEKDAYS) + r")\b")
_MONTH_DAY = re.compile(
    r"\b(" + "|".join(_MONTHS + [m[:3] for m in _MONTHS]) +
    r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b"
)
_TIME = re.compile(
    r"\b(?:at\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?"
    r"\s*(?P<period>am|pm)\b|"
    r"\bat\s+(?P<bare_hour>\d{1,2})(?::(?P<bare_minute>\d{2}))?\b|"
    r"(?<![\dT:])(?P<clock_hour>\d{1,2}):(?P<clock_minute>\d{2})(?![:\d])"
)
_ISO_STAMP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}(?::\d{2})?(?:z|[+-]\d{2}:\d{2})?\b"
)


def _normalize_relative(text: str) -> str:
    # Deliberately narrow spelling aliases, never fuzzy-match arbitrary words.
    return re.sub(r"\b(?:tonmorow|tomorow|tommorow|tommorrow)\b", "tomorrow", text, flags=re.I)


def _explicit_year(text: str) -> int | None:
    years = {int(m.group()[:4]) for m in _ISO_DAY.finditer(text)}
    for match in _NUMERIC_DAY.finditer(text):
        if match["year"]:
            years.add(int(match["year"]) + (2000 if len(match["year"]) == 2 else 0))
    years.update(int(m[3]) for m in _MONTH_DAY.finditer(text.lower()) if m[3])
    return next(iter(years)) if len(years) == 1 else None


def _supply_year(text: str, year: int | None) -> str:
    if year is None:
        return text
    text = _NUMERIC_DAY.sub(lambda m: m.group() if m["year"] else f"{m.group()}{m['sep']}{year:04}", text)
    return _MONTH_DAY.sub(lambda m: m.group() if m[3] else f"{m.group()} {year:04}", text.lower())


def _time_matches(text: str):
    masked = _ISO_DAY.sub(lambda m: " " * len(m.group()), text.lower())
    masked = _NUMERIC_DAY.sub(lambda m: " " * len(m.group()), masked)
    return _TIME.finditer(masked)


def _strip_times(text: str) -> str:
    for match in reversed(list(_time_matches(text))):
        text = text[:match.start()] + text[match.end():]
    return text


def has_date_language(text: str) -> bool:
    text = _normalize_relative(text)
    return bool(re.search(
        r"\b(today|tomorrow|yesterday|week|month|year|tonight|weekend|"
        + "|".join(_WEEKDAYS + _MONTHS) + r")\b", text, re.I
    ) or _ISO_DAY.search(text) or _NUMERIC_DAY.search(text))


def calendar_question(text: str) -> bool:
    lower = text.lower().strip()
    question = bool(re.match(r"(?:what|when|show|list|do i|am i|is there|any)\b", lower))
    calendar = bool(re.search(r"\b(calendar|schedule|agenda|meetings?|appointments?|events?)\b", lower))
    return question and (calendar or (has_date_language(lower) and not local_search_question(lower)))


def local_search_question(text: str) -> bool:
    return bool(re.search(r"\b(notes?|links?|captures?|saved|wrote|captured)\b", text, re.I))


def _abbreviation(text: str) -> str | None:
    foreign_zone = re.search(r"\b(PST|PDT|CST|CDT|MST|MDT|UTC|GMT|BST|CET|CEST|IST|JST|AEST|AEDT)\b", text.upper())
    named_zones = re.findall(r"\b[A-Za-z_]+/[A-Za-z_]+\b", text)
    if foreign_zone or any(zone != config.TIMEZONE for zone in named_zones):
        raise ClarificationNeeded(f"Please give the time in {config.TIMEZONE}, or an ISO date/time with a UTC offset.")
    abbreviations = set(re.findall(r"\b(EST|EDT)\b", text.upper()))
    if len(abbreviations) > 1:
        raise ClarificationNeeded("Which timezone do you mean, EDT or EST? Please specify just one.")
    return next(iter(abbreviations)) if abbreviations else None


def _span(text: str, now: datetime, *, week_context: DateSpan | None = None) -> DateSpan | None:
    lower = _normalize_relative(text).lower()
    spans = []
    try:
        for match in _NUMERIC_DAY.finditer(lower):
            first, second = int(match["first"]), int(match["second"])
            month, day_number = (second, first) if first > 12 and match["sep"] == "/" else (first, second)
            year = int(match["year"]) if match["year"] else now.year
            if match["year"] and len(match["year"]) == 2:
                year += 2000
            day = date(year, month, day_number)
            spans.append(DateSpan(day, day + timedelta(days=1), inferred_year=not match["year"]))
        for match in _ISO_DAY.finditer(lower):
            day = date.fromisoformat(match.group())
            spans.append(DateSpan(day, day + timedelta(days=1)))
        for match in _MONTH_DAY.finditer(lower):
            month = next(i + 1 for i, name in enumerate(_MONTHS) if name.startswith(match[1]))
            day = date(int(match[3]) if match[3] else now.year, month, int(match[2]))
            spans.append(DateSpan(day, day + timedelta(days=1), inferred_year=not match[3]))
    except ValueError as exc:
        if isinstance(exc, ClarificationNeeded):
            raise
        raise ClarificationNeeded("That date is not valid. What exact date should I use?") from None

    for match in re.finditer(r"\b(day after tomorrow|tomorrow|today|tonight|yesterday)\b", lower):
        delta = {"day after tomorrow": 2, "tomorrow": 1, "today": 0, "tonight": 0, "yesterday": -1}[match.group()]
        day = now.date() + timedelta(days=delta)
        spans.append(DateSpan(day, day + timedelta(days=1)))

    week_match = re.search(r"\b(this|next) week\b", lower)
    if week_match:
        monday = now.date() - timedelta(days=now.weekday())
        if week_match[1] == "next":
            monday += timedelta(days=7)
        spans.append(DateSpan(monday, monday + timedelta(days=7)))
    elif re.search(r"\bnext (?:7|seven) days\b", lower):
        spans.append(DateSpan(now.date(), now.date() + timedelta(days=7)))

    for match in _WEEKDAY.finditer(lower):
        weekday = _WEEKDAYS.index(match[2])
        context = week_context
        if week_match:
            context = DateSpan(monday, monday + timedelta(days=7))
            if context in spans:
                spans.remove(context)
        if len(set(spans)) == 1 and (spans[0].end - spans[0].start).days == 1:
            day = spans[0].start
            if day.weekday() != weekday:
                raise ClarificationNeeded(
                    f"{day:%A, %B %d, %Y} is not {match[2].title()}. "
                    "Please confirm the weekday and date together, for example Saturday 10-31-2026."
                )
            continue
        if context and not match[1]:
            day = context.start + timedelta(days=weekday)
        elif match[1] == "this":
            day = now.date() - timedelta(days=now.weekday()) + timedelta(days=weekday)
            if day < now.date():
                raise ClarificationNeeded("That weekday in this week has passed. Which date do you mean? Use MM-DD-YYYY.")
        elif match[1] == "next":
            day = now.date() - timedelta(days=now.weekday()) + timedelta(days=7 + weekday)
        else:
            day = now.date() + timedelta(days=(weekday - now.weekday()) % 7)
        spans.append(DateSpan(day, day + timedelta(days=1)))

    unique = set(spans)
    if len(unique) > 1:
        raise ClarificationNeeded("I found conflicting dates or a date range. Which single date or week should I use?")
    if not unique:
        return None
    # Do not silently ignore a second, unsupported temporal qualifier.
    if re.search(r"\b(weekend|month|year)\b|\bin \d+ (?:days?|weeks?)\b", _NUMERIC_DAY.sub("", lower)):
        raise ClarificationNeeded("Please give a date such as November 12, 11-12-2026, tomorrow, or Saturday.")
    return unique.pop()


def _clock(text: str) -> time | None:
    lower = text.lower()
    stamps = list(_ISO_STAMP.finditer(lower))
    if stamps:
        if len(stamps) != 1:
            raise ClarificationNeeded("Please give one event start date/time.")
        stamp = stamps[0]
        try:
            value = datetime.fromisoformat(stamp.group().upper())
        except ValueError:
            raise ClarificationNeeded("Please give a valid ISO date/time.") from None
        remaining = _clock(text[:stamp.start()] + text[stamp.end():])
        clock = value.time().replace(tzinfo=None)
        if remaining is not None and remaining != clock:
            raise ClarificationNeeded("Please give one start time.")
        return clock
    times = set()
    for match in _time_matches(lower):
        if match["hour"] is not None:
            hour, minute = int(match["hour"]), int(match["minute"] or 0)
            if not 1 <= hour <= 12:
                raise ClarificationNeeded("Please give a valid time with AM/PM or a 24-hour time.")
            hour = hour % 12 + (12 if match["period"] == "pm" else 0)
        else:
            raw_hour = match["bare_hour"] or match["clock_hour"]
            raw_minute = match["bare_minute"] or match["clock_minute"]
            hour, minute = int(raw_hour), int(raw_minute or 0)
            if 1 <= hour <= 12 and not (raw_minute and raw_hour.startswith("0")):
                raise ClarificationNeeded("Is that AM or PM? Please reply with a time such as 5pm or 17:00.")
        try:
            times.add(time(hour, minute))
        except ValueError:
            raise ClarificationNeeded("Please give a valid time with AM/PM or a 24-hour time.") from None
    if re.search(r"\bnoon\b", lower):
        times.add(time(12))
    if re.search(r"\bmidnight\b", lower):
        times.add(time())
    if len(times) > 1:
        raise ClarificationNeeded("Please give one start time. Timed events currently last one hour.")
    return next(iter(times)) if times else None


def _all_day(text: str) -> bool:
    return bool(re.search(r"\ball[ -]day\b", text, re.I))


def _merged_instant(day: date, clock: time, text: str, answer: str) -> datetime:
    """A reply replaces only the components it actually supplies."""
    abbreviation = _abbreviation(answer) or _abbreviation(text)
    source = answer if _ISO_STAMP.search(answer.lower()) else text
    stamp = _ISO_STAMP.search(source.lower())
    if stamp and not abbreviation and config.TIMEZONE not in answer:
        value = datetime.fromisoformat(stamp.group().upper())
        if value.tzinfo is not None:
            return datetime.combine(day, clock, value.tzinfo).astimezone(ZoneInfo(config.TIMEZONE))
    return localize(datetime.combine(day, clock), abbreviation)


def _check_weekday(original: str, answer: str, span: DateSpan) -> None:
    """A date-only correction must not silently discard an established weekday."""
    weekdays = list(_WEEKDAY.finditer(answer.lower())) or list(_WEEKDAY.finditer(original.lower()))
    if (span.end - span.start).days != 1:
        return
    for match in weekdays:
        if span.start.weekday() != _WEEKDAYS.index(match[2]):
            raise ClarificationNeeded(
                f"{span.start:%A, %B %d, %Y} is not {match[2].title()}. "
                "Please confirm the weekday and date together (MM-DD-YYYY)."
            )


def _resolved_span(text: str, answer: str, reference: datetime) -> tuple[DateSpan | None, DateSpan | None]:
    week = re.search(r"\b(this|next) week\b", text, re.I)
    context = _span(week.group(), reference) if week else None
    reply = _supply_year(answer, _explicit_year(text))
    reply_span = _span(reply, reference, week_context=context) if reply else None
    span = reply_span or _span(text, reference)
    if span is not None:
        _check_weekday(text, reply, span)
    return span, reply_span


def _check_inferred_past(span: DateSpan, reference: datetime, instant: datetime | None = None) -> None:
    if span.inferred_year and (span.start < reference.date() or (
        instant is not None and instant.astimezone(timezone.utc) <= reference.astimezone(timezone.utc)
    )):
        raise ClarificationNeeded(
            f"{span.start:%B %d, %Y} would be in the past using the current year. "
            "Which year do you mean? Please include it as MM-DD-YYYY."
        )


def _upcoming_weekday(value: datetime, span: DateSpan, text: str, answer: str,
                      reply_span: DateSpan | None, reference: datetime, clock: time) -> datetime:
    source = answer if reply_span else text
    weekdays = list(_WEEKDAY.finditer(source.lower()))
    if (weekdays and all(m[1] is None for m in weekdays)
            and not (_ISO_DAY.search(source) or _NUMERIC_DAY.search(source)
                     or _MONTH_DAY.search(source.lower()) or re.search(r"\bweek\b", text + " " + answer, re.I))
            and value.astimezone(timezone.utc) <= reference.astimezone(timezone.utc)):
        return _merged_instant(span.start + timedelta(days=7), clock, text, answer)
    return value


def resolve_event(text: str, now: datetime | None = None, *, answer: str = "") -> str:
    text, answer = _normalize_relative(text), _normalize_relative(answer)
    reference = local_reference(now)
    span, reply_span = _resolved_span(text, answer, reference)
    if span is not None:
        _check_inferred_past(span, reference)
    # ISO timestamps explicitly use a 24-hour clock; offsets resolve DST folds.
    source = answer if _ISO_STAMP.search(answer.lower()) else (text if not answer else "")
    stamps = list(_ISO_STAMP.finditer(source.lower()))
    if stamps:
        if len(stamps) != 1:
            raise ClarificationNeeded("Please give one event start date/time.")
        stamp = stamps[0]
        _span(source, reference)  # reject conflicting date expressions
        remainder = source[:stamp.start()] + source[stamp.end():]
        if _TIME.search(remainder.lower()):
            raise ClarificationNeeded("Please give one event start time.")
        try:
            value = datetime.fromisoformat(stamp.group().upper())
        except ValueError:
            raise ClarificationNeeded("Please give a valid ISO date/time with a UTC offset.") from None
        if _all_day(text) or _all_day(answer):
            raise ClarificationNeeded("Should this be all day, or use the supplied time?")
        if value.tzinfo is None:
            value = localize(value, _abbreviation(source))
        else:
            value = value.astimezone(reference.tzinfo)
            abbreviation = _abbreviation(remainder)
            if abbreviation and abbreviation != value.tzname():
                raise ClarificationNeeded("The UTC offset and timezone abbreviation disagree. Which one should I use?")
        return value.isoformat()

    # A reply can replace a component the first message left ambiguous.
    if span is None:
        raise ClarificationNeeded("What date is the event? Please reply with a full date or a phrase such as tomorrow.")
    if (span.end - span.start).days != 1:
        raise ClarificationNeeded("Which date in that week is the event? A weekday or MM-DD-YYYY is fine.")

    all_day = _all_day(answer) or (_all_day(text) and not _TIME.search(answer.lower()))
    reply_clock = _clock(answer) if answer else None
    clock = reply_clock if reply_clock is not None else (None if all_day else _clock(text))
    if all_day:
        if reply_clock is not None or (not _all_day(answer) and _TIME.search(text.lower())):
            raise ClarificationNeeded("Should this be all day, or use the supplied time?")
        return span.start.isoformat()
    if clock is None:
        raise ClarificationNeeded("What time is the event? Please reply with AM/PM or say all day.")
    value = _merged_instant(span.start, clock, text, answer)
    value = _upcoming_weekday(value, span, text, answer, reply_span, reference, clock)
    _check_inferred_past(span, reference, value)
    relative_source = answer if reply_span else text
    if re.search(r"\b(today|tonight|tomorrow|this)\b", relative_source, re.I):
        if value.astimezone(timezone.utc) <= reference.astimezone(timezone.utc):
            raise ClarificationNeeded("That date/time has already passed. What exact date and time should I use?")
    return value.isoformat()


def resolve_query(text: str, now: datetime | None = None, *, answer: str = "") -> DateSpan:
    reference = local_reference(now)
    span, reply_span = _resolved_span(text, answer, reference)
    if span is None:
        raise ClarificationNeeded("Which date or week should I check? Try tomorrow, this Friday, or next week.")
    whole_day = bool(re.search(r"\bwhole day\b", answer, re.I)) or _all_day(answer)
    if whole_day:
        return span
    source = answer if _ISO_STAMP.search(answer.lower()) else (text if not answer else "")
    if _ISO_STAMP.search(source.lower()):
        instant = datetime.fromisoformat(resolve_event(source, reference))
        return DateSpan(instant.date(), instant.date() + timedelta(days=1), instant)
    reply_clock = _clock(answer) if answer else None
    clock = reply_clock if reply_clock is not None else _clock(text)
    if clock is not None:
        if (span.end - span.start).days != 1:
            raise ClarificationNeeded("Which date in that week should I check at that time?")
        instant = _merged_instant(span.start, clock, text, answer)
        instant = _upcoming_weekday(instant, span, text, answer, reply_span, reference, clock)
        return DateSpan(instant.date(), instant.date() + timedelta(days=1), instant)
    return span


def describe_span(span: DateSpan) -> str:
    if span.at is not None:
        return f"At {span.at:%a %Y-%m-%d %I:%M %p %Z} (UTC{span.at:%z}; {config.TIMEZONE})"
    start, end = span.bounds()
    return (f"{start:%a %Y-%m-%d %H:%M %Z} to {end:%a %Y-%m-%d %H:%M %Z} "
            f"(end exclusive; {config.TIMEZONE})")


def event_end(start: datetime) -> datetime:
    """One elapsed hour, including when local clocks change."""
    return (start.astimezone(timezone.utc) + timedelta(hours=1)).astimezone(start.tzinfo)
