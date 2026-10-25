from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import icalendar
import pytest

from hellweek.classify import Classification, classify_events
from hellweek.make_demo import build_calendar
from hellweek.parse import Event, expand_events

SEMESTER_START = date(2026, 8, 25)
SEMESTER_END = date(2026, 12, 15)
NEW_YORK = ZoneInfo("America/New_York")


@pytest.fixture(scope="session")
def demo_calendar() -> icalendar.Calendar:
    # Round-trip through text so tests see exactly what a .ics file would contain.
    return icalendar.Calendar.from_ical(build_calendar().to_ical())


@pytest.fixture(scope="session")
def demo_events(demo_calendar: icalendar.Calendar) -> list[Event]:
    return expand_events(demo_calendar, SEMESTER_START, SEMESTER_END, NEW_YORK)


@pytest.fixture(scope="session")
def demo_classes(demo_events: list[Event]) -> dict[str, Classification]:
    return classify_events(demo_events)


def make_event(title: str, start: datetime, hours: float = 1.0, all_day: bool = False) -> Event:
    return Event(
        id=f"{title}_{start.isoformat()}",
        title=title,
        start=start,
        end=start + timedelta(hours=hours),
        all_day=all_day,
        duration_hours=0.0 if all_day else hours,
        location="",
        description="",
    )
