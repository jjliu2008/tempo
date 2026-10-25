from datetime import date, datetime, timedelta

import pytest

from hellweek.classify import Classification, classify_events
from hellweek.load import compute_daily_load, lead_days, split_by_day, spread_prep
from hellweek.parse import Event

from .conftest import NEW_YORK, SEMESTER_END, SEMESTER_START, make_event


def test_spread_prep_ramps_toward_event() -> None:
    spread = spread_prep(date(2026, 10, 20), 10.0, 4, SEMESTER_START, SEMESTER_END)
    assert spread == {
        date(2026, 10, 16): 1.0,
        date(2026, 10, 17): 2.0,
        date(2026, 10, 18): 3.0,
        date(2026, 10, 19): 4.0,
    }


@pytest.mark.parametrize("event_type", ["exam", "deadline", "quiz", "other", "meeting"])
@pytest.mark.parametrize("days_in", [0, 1, 2, 3, 4, 5, 6, 30])
def test_spread_prep_preserves_total_including_clipping(event_type: str, days_in: int) -> None:
    event_day = SEMESTER_START + timedelta(days=days_in)
    lead = lead_days(event_type)
    spread = spread_prep(event_day, 7.5, lead, SEMESTER_START, SEMESTER_END)
    assert sum(spread.values()) == pytest.approx(7.5)
    assert all(SEMESTER_START <= d <= event_day for d in spread)
    # Prep only lands on the event day itself when no earlier day is in range.
    assert (event_day in spread) == (days_in == 0)


def test_clipped_spread_renormalizes_kept_weights() -> None:
    # Exam on day 3: lead days are Aug 23-26 with weights 1..4; only Aug 25 (3) and 26 (4) survive.
    spread = spread_prep(date(2026, 8, 27), 7.0, 4, SEMESTER_START, SEMESTER_END)
    assert spread == {date(2026, 8, 25): pytest.approx(3.0), date(2026, 8, 26): pytest.approx(4.0)}


def test_spread_prep_ignores_events_outside_range() -> None:
    assert spread_prep(date(2026, 8, 24), 10.0, 4, SEMESTER_START, SEMESTER_END) == {}
    assert spread_prep(date(2026, 10, 20), 0.0, 4, SEMESTER_START, SEMESTER_END) == {}


def test_daily_load_preserves_prep_when_clipped_at_semester_start() -> None:
    exam = make_event("CHEM Exam", datetime(2026, 8, 26, 9, tzinfo=NEW_YORK), hours=2)
    events = [exam]
    days = compute_daily_load(events, classify_events(events), SEMESTER_START, SEMESTER_END)
    assert sum(d.prep_hours for d in days) == pytest.approx(10.0)
    assert sum(d.scheduled_hours for d in days) == pytest.approx(2.0)
    assert days[0].prep_hours == pytest.approx(10.0)


def test_daily_load_covers_every_day_and_all_prep(
    demo_events: list[Event], demo_classes: dict[str, Classification]
) -> None:
    days = compute_daily_load(demo_events, demo_classes, SEMESTER_START, SEMESTER_END)
    assert [d.date for d in days] == [
        SEMESTER_START + timedelta(days=i) for i in range((SEMESTER_END - SEMESTER_START).days + 1)
    ]
    assert any(d.total_hours == 0 for d in days)
    assert sum(d.prep_hours for d in days) == pytest.approx(
        sum(c.prep_hours for c in demo_classes.values())
    )
    assert sum(d.scheduled_hours for d in days) == pytest.approx(
        sum(e.duration_hours for e in demo_events)
    )


def test_all_day_event_adds_prep_but_no_scheduled_hours() -> None:
    due = make_event("Essay due", datetime(2026, 10, 30, tzinfo=NEW_YORK), all_day=True)
    days = compute_daily_load([due], classify_events([due]), SEMESTER_START, SEMESTER_END)
    by_date = {d.date: d for d in days}
    assert by_date[date(2026, 10, 30)].scheduled_hours == 0
    assert sum(d.prep_hours for d in days) == pytest.approx(6.0)


def test_split_by_day_across_midnight() -> None:
    start = datetime(2026, 10, 9, 22, tzinfo=NEW_YORK)
    assert split_by_day(start, start + timedelta(hours=4)) == {
        date(2026, 10, 9): 2.0,
        date(2026, 10, 10): 2.0,
    }


def test_split_by_day_counts_real_hours_on_dst_night() -> None:
    # Clocks fall back at 2:00 on Nov 1, so midnight to 6:00 local is 7 real hours.
    start = datetime(2026, 11, 1, 0, tzinfo=NEW_YORK)
    end = datetime(2026, 11, 1, 6, tzinfo=NEW_YORK)
    assert split_by_day(start, end) == {date(2026, 11, 1): 7.0}
