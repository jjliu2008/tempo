"""Workload analysis for the web app: load the events, then run the hellweek pipeline.

Synchronous on purpose (calendar fetch and Gemma calls block), so the endpoint
runs it in a worker thread. Logs carry counts only: never titles or the URL.
"""

import logging
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import icalendar

from app.core.config import Settings
from app.schemas.analysis import CalendarAnalyzeRequest, InputEvent
from hellweek.gemma import DEFAULT_MODELS, GemmaClient
from hellweek.make_demo import build_calendar
from hellweek.parse import (
    Event,
    calendar_timezone,
    elapsed_hours,
    expand_events,
    is_url,
    parse_ics,
    read_calendar,
)
from hellweek.pipeline import analysis_json, analyze

logger = logging.getLogger(__name__)

DEMO_RANGE = (date(2026, 8, 25), date(2026, 12, 15))
MAX_ICS_CHARS = 5_000_000
MAX_RANGE_DAYS = 400
MAX_EVENTS = 20_000
GEMMA_CACHE = Path(__file__).resolve().parents[2] / ".gemma_cache.json"


class CalendarRequestError(Exception):
    """A bad request. Messages are safe to show and never include the URL."""


@lru_cache(maxsize=8)
def demo_ics(variant: str = "engineering") -> bytes:
    data: bytes = build_calendar(variant).to_ical()
    return data


def local(moment: datetime, tz: ZoneInfo) -> datetime:
    return moment.replace(tzinfo=tz) if moment.tzinfo is None else moment.astimezone(tz)


def to_event(item: InputEvent, tz: ZoneInfo) -> Event:
    start, end = local(item.start, tz), local(item.end, tz)
    if item.all_day:
        # All-day items keep their calendar date, whatever offset they were sent with.
        start = datetime.combine(item.start.date(), time(), tz)
        end = datetime.combine(item.end.date(), time(), tz)
    return Event(
        id=item.id,
        title=item.title.strip() or "(untitled)",
        start=start,
        end=max(end, start),
        all_day=item.all_day,
        duration_hours=0.0 if item.all_day else max(0.0, elapsed_hours(start, end)),
        location="",
        description="",
    )


def parsed_events(
    request: CalendarAnalyzeRequest, start: date, end: date, tz: ZoneInfo
) -> list[Event]:
    items = request.events or []
    if not items:
        raise CalendarRequestError("There are no events to analyze.")
    if len(items) > MAX_EVENTS:
        raise CalendarRequestError(f"That is more than {MAX_EVENTS} events.")
    events = [to_event(item, tz) for item in items]
    inside = [e for e in events if start <= e.start.date() <= end or start <= e.end.date() <= end]
    return sorted(inside, key=lambda e: (e.start, e.id))


def load_calendar(request: CalendarAnalyzeRequest) -> icalendar.Calendar:
    if request.source == "demo":
        return parse_ics(demo_ics(request.demo), "demo calendar")
    if request.source == "ics":
        if not request.ics or not request.ics.strip():
            raise CalendarRequestError("Upload an .ics file.")
        if len(request.ics) > MAX_ICS_CHARS:
            raise CalendarRequestError("That calendar file is over 5 MB.")
        return parse_ics(request.ics.encode("utf-8"), "uploaded calendar")
    url = (request.url or "").strip()
    if not is_url(url):
        raise CalendarRequestError("Calendar URLs must start with https:// or webcal://.")
    return read_calendar(url)


def date_range(request: CalendarAnalyzeRequest) -> tuple[date, date]:
    if request.source == "demo":
        start, end = request.start or DEMO_RANGE[0], request.end or DEMO_RANGE[1]
    elif request.start is None or request.end is None:
        raise CalendarRequestError("Choose a start and end date.")
    else:
        start, end = request.start, request.end
    if start > end:
        raise CalendarRequestError("The start date must be on or before the end date.")
    if (end - start).days > MAX_RANGE_DAYS:
        raise CalendarRequestError(f"Pick a range of at most {MAX_RANGE_DAYS} days.")
    return start, end


def gemma_client(settings: Settings) -> GemmaClient | None:
    key = settings.GOOGLE_API_KEY
    if key is None or not key.get_secret_value().strip():
        return None
    models = (settings.GEMMA_MODEL, *(m for m in DEFAULT_MODELS if m != settings.GEMMA_MODEL))
    return GemmaClient(key.get_secret_value().strip(), models=models)


def analyze_calendar(request: CalendarAnalyzeRequest, settings: Settings) -> dict[str, Any]:
    start, end = date_range(request)
    cal = None if request.source == "events" else load_calendar(request)
    tz_name = request.tz or (calendar_timezone(cal) if cal else None) or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise CalendarRequestError(f"Unknown timezone: {tz_name}") from None
    if cal is None:
        events = parsed_events(request, start, end, tz)
    else:
        events = expand_events(cal, start, end, tz)
    client = gemma_client(settings) if request.gemma else None
    if request.gemma and client is None:
        logger.info("Gemma requested but GOOGLE_API_KEY is not set; using keyword rules")
    result = analyze(
        events, start, end, tz_name, gemma=client, gemma_cache=GEMMA_CACHE, log=logger.info
    )
    logger.info(
        "analyzed %d events over %d days: %d hell weeks (%s)",
        len(events),
        len(result.days),
        len(result.detection.hell_weeks),
        result.classifier,
    )
    return analysis_json(result)
