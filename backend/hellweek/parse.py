"""Parse an .ics calendar into a flat list of timezone-aware event occurrences."""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events  # type: ignore[import-untyped]
import x_wr_timezone  # type: ignore[import-untyped]

DEFAULT_DURATION = timedelta(hours=1)


@dataclass(frozen=True)
class Event:
    id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    duration_hours: float
    location: str
    description: str

    def to_dict(self) -> dict[str, str | bool | float]:
        return {
            "id": self.id,
            "title": self.title,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "all_day": self.all_day,
            "duration_hours": self.duration_hours,
            "location": self.location,
            "description": self.description,
        }


def read_calendar(source: str | Path) -> icalendar.Calendar:
    """Load a calendar from a file path or an http(s)/webcal URL."""
    text = str(source)
    if text.startswith(("http://", "https://", "webcal://")):
        url = "https://" + text[len("webcal://") :] if text.startswith("webcal://") else text
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
    else:
        data = Path(source).read_bytes()
    return icalendar.Calendar.from_ical(data)


def fill_missing_ends(cal: icalendar.Calendar) -> icalendar.Calendar:
    """Give timed events with neither DTEND nor DURATION a 1-hour duration.

    Done before expansion because recurring-ical-events fills in a zero-length
    end, after which a missing end can't be told apart from a real one.
    """
    for comp in cal.walk("VEVENT"):
        has_end = "DTEND" in comp or "DURATION" in comp
        if not has_end and isinstance(comp.decoded("DTSTART"), datetime):
            comp.add("DURATION", DEFAULT_DURATION)
    return cal


def to_local(value: date | datetime, tz: ZoneInfo) -> datetime:
    """Convert an iCal date/datetime to an aware datetime in tz.

    Floating (naive) times are taken to already be in tz; dates become local midnight.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=tz) if value.tzinfo is None else value.astimezone(tz)
    return datetime.combine(value, time(), tz)


def elapsed_hours(start: datetime, end: datetime) -> float:
    """Real elapsed hours. Subtracting two datetimes that share a ZoneInfo ignores
    DST offsets, so compare in UTC instead."""
    delta = end.astimezone(UTC) - start.astimezone(UTC)
    return delta.total_seconds() / 3600


def occurrence_id(uid: str, start: datetime, all_day: bool) -> str:
    """Stable id per occurrence. Timed starts are keyed in UTC so the id doesn't
    change when --tz does (classes.json must still match)."""
    start_iso = start.date().isoformat() if all_day else start.astimezone(UTC).isoformat()
    return f"{uid}_{start_iso}"


def to_event(comp: icalendar.Event, tz: ZoneInfo) -> Event | None:
    """Turn one expanded occurrence into an Event, or None if it is cancelled."""
    if str(comp.get("STATUS", "")).upper() == "CANCELLED":
        return None
    raw_start = comp.decoded("DTSTART")
    all_day = not isinstance(raw_start, datetime)
    start = to_local(raw_start, tz)
    if "DTEND" in comp:
        end = to_local(comp.decoded("DTEND"), tz)
    elif "DURATION" in comp:
        end = (start.astimezone(UTC) + comp.decoded("DURATION")).astimezone(tz)
    else:
        end = start + (timedelta(days=1) if all_day else DEFAULT_DURATION)
    title = str(comp.get("SUMMARY", "")).strip() or "(untitled)"
    uid = str(comp.get("UID", "")).strip() or f"nouid-{title}"
    return Event(
        id=occurrence_id(uid, start, all_day),
        title=title,
        start=start,
        end=end,
        all_day=all_day,
        duration_hours=0.0 if all_day else max(0.0, elapsed_hours(start, end)),
        location=str(comp.get("LOCATION", "")).strip(),
        description=str(comp.get("DESCRIPTION", "")).strip(),
    )


def expand_events(cal: icalendar.Calendar, start: date, end: date, tz: ZoneInfo) -> list[Event]:
    """Expand recurrences and return every non-cancelled occurrence touching [start, end]."""
    cal = fill_missing_ends(x_wr_timezone.to_standard(cal))
    window_start = datetime.combine(start, time(), tz)
    window_end = datetime.combine(end + timedelta(days=1), time(), tz)
    events: dict[str, Event] = {}
    for comp in recurring_ical_events.of(cal).between(window_start, window_end):
        event = to_event(comp, tz)
        if event is not None:
            events.setdefault(event.id, event)
    return sorted(events.values(), key=lambda e: (e.start, e.id))


def parse_calendar(source: str | Path, start: date, end: date, tz_name: str) -> list[Event]:
    return expand_events(read_calendar(source), start, end, ZoneInfo(tz_name))
