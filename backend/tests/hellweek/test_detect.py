from datetime import date, datetime, timedelta

from hellweek.classify import Classification
from hellweek.detect import (
    Window,
    detect_hell_weeks,
    is_flagged,
    load_threshold,
    merge_overlapping,
)
from hellweek.load import BreakdownItem, DayLoad, compute_daily_load
from hellweek.make_demo import WEEK_9_START
from hellweek.parse import Event

from .conftest import NEW_YORK, SEMESTER_END, SEMESTER_START, make_event

WEEK_9_END = WEEK_9_START + timedelta(days=6)


def window(start: date, hours: float, stressors: int) -> Window:
    return Window(
        start, start + timedelta(days=6), hours, frozenset(f"e{i}" for i in range(stressors))
    )


def test_demo_calendar_flags_week_9_as_only_hell_week(
    demo_events: list[Event], demo_classes: dict[str, Classification]
) -> None:
    days = compute_daily_load(demo_events, demo_classes, SEMESTER_START, SEMESTER_END)
    result = detect_hell_weeks(days, demo_events, demo_classes)

    assert len(result.hell_weeks) == 1
    week = result.hell_weeks[0]
    assert week.start <= WEEK_9_END and week.end >= WEEK_9_START
    assert week.peak.total_hours > result.threshold >= 50
    assert {k.title for k in week.key_events} == {
        "CHEM 210 Midterm 1",
        "MATH 241 Midterm",
        "CS 220 Project 2 due",
    }
    assert all(WEEK_9_START <= k.date <= WEEK_9_END for k in week.key_events)


def test_flag_needs_both_load_and_two_stressors() -> None:
    start = date(2026, 10, 1)
    assert is_flagged(window(start, 60, 2), threshold=50)
    assert not is_flagged(window(start, 60, 1), threshold=50)
    assert not is_flagged(window(start, 50, 3), threshold=50)


def test_threshold_is_max_of_floor_and_scaled_median() -> None:
    start = date(2026, 10, 1)
    light = [window(start, h, 0) for h in (10, 20, 30)]
    heavy = [window(start, h, 0) for h in (40, 45, 60)]
    assert load_threshold(light) == (50, 20)
    assert load_threshold(heavy) == (1.4 * 45, 45)


def test_overlapping_windows_merge_and_gaps_split() -> None:
    d = date(2026, 10, 1)
    starts = [d, d + timedelta(days=3), d + timedelta(days=10)]
    runs = merge_overlapping([window(s, 60, 2) for s in starts])
    assert [len(r) for r in runs] == [2, 1]


def test_hell_weeks_rank_by_peak_window() -> None:
    start = date(2026, 9, 1)
    days = [DayLoad(start + timedelta(days=i)) for i in range(60)]
    events: list[Event] = []
    classes: dict[str, Classification] = {}

    def stressor(day_index: int, hours_per_day: float, name: str) -> None:
        day = days[day_index].date
        event = make_event(name, datetime(day.year, day.month, day.day, 9, tzinfo=NEW_YORK))
        events.append(event)
        classes[event.id] = Classification("exam", 0.0, 9)
        for d in days[day_index - 3 : day_index + 1]:
            d.breakdown.append(BreakdownItem(event.id, name, "prep", hours_per_day))

    stressor(10, 8, "A1")
    stressor(11, 8, "A2")  # ~64h week
    stressor(40, 12, "B1")
    stressor(41, 12, "B2")  # ~96h week, later in the term
    result = detect_hell_weeks(days, events, classes)
    assert [sorted(k.title for k in h.key_events) for h in result.hell_weeks] == [
        ["B1", "B2"],
        ["A1", "A2"],
    ]
