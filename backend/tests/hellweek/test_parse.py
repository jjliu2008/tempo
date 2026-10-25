from datetime import date, time
from pathlib import Path

import pytest

from hellweek.parse import Event, parse_calendar

FIXTURE = Path(__file__).parent / "fixtures" / "edge_cases.ics"


@pytest.fixture(scope="module")
def events() -> list[Event]:
    return parse_calendar(FIXTURE, date(2026, 10, 1), date(2026, 11, 30), "America/New_York")


def by_title(events: list[Event], title: str) -> list[Event]:
    return [e for e in events if e.title == title]


def test_weekly_recurring_event_expands_to_right_count(events: list[Event]) -> None:
    # Tuesdays Oct 6 - Nov 24 is 8 occurrences, minus the cancelled Oct 20.
    lectures = by_title(events, "CHEM 101 Lecture")
    assert len(lectures) == 7
    assert date(2026, 10, 20) not in {e.start.date() for e in lectures}


def test_series_crossing_dst_keeps_local_time(events: list[Event]) -> None:
    lectures = by_title(events, "CHEM 101 Lecture")
    assert {e.start.time() for e in lectures} == {time(10, 0)}
    assert {e.start.tzname() for e in lectures} == {"EDT", "EST"}
    assert {e.duration_hours for e in lectures} == {1.25}


def test_all_day_event_counts_zero_scheduled_hours(events: list[Event]) -> None:
    (essay,) = by_title(events, "History essay due")
    assert essay.all_day
    assert essay.duration_hours == 0.0
    assert essay.id == "essay-due_2026-10-30"


def test_missing_end_defaults_to_one_hour(events: list[Event]) -> None:
    (office_hours,) = by_title(events, "Office hours")
    assert office_hours.duration_hours == 1.0


def test_cancelled_event_is_skipped(events: list[Event]) -> None:
    assert by_title(events, "Halloween party") == []
