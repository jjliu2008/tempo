from datetime import date, datetime

import pytest

from hellweek.classify import Classification
from hellweek.load import BreakdownItem, DayLoad, compute_daily_load
from hellweek.parse import Event
from hellweek.pipeline import analysis_json, analyze
from hellweek.plan import fill, free_intervals, plan_prep

from .conftest import NEW_YORK, SEMESTER_END, SEMESTER_START, make_event

DAY = date(2026, 10, 19)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=NEW_YORK)


def test_free_intervals_align_to_quarter_hours_and_skip_short_gaps() -> None:
    busy = [(9.0, 9 + 50 / 60), (10.0, 11.0), (11.25, 12.0)]
    assert free_intervals(busy, 9.0, 14.0) == [(12.0, 14.0)]
    assert free_intervals([(9.5, 10.0)], 9.0, 12.0) == [(9.0, 9.5), (10.0, 12.0)]
    assert free_intervals([], 9.0, 26.0) == [(9.0, 26.0)]


def test_fill_splits_across_gaps_and_reports_overflow() -> None:
    blocks, unplaced = fill([("e1", "Exam", 3.0)], [(9.0, 10.0), (12.0, 13.5)], DAY)
    assert [(b.start, b.end) for b in blocks] == [(9.0, 10.0), (12.0, 13.5)]
    assert unplaced == pytest.approx(0.5)


def test_prep_blocks_avoid_scheduled_events() -> None:
    lecture = make_event("Lecture", at(9), hours=3)
    day = DayLoad(DAY, [BreakdownItem("exam-id", "Midterm", "prep", 4.0)])
    blocks, unplaced = plan_prep([day], [lecture], NEW_YORK)
    assert unplaced == 0
    assert [(b.start, b.end, b.event_id) for b in blocks] == [(12.0, 16.0, "exam-id")]


def test_packed_day_spills_into_late_night() -> None:
    work = make_event("Shift", at(9), hours=14)  # 9:00-23:00
    day = DayLoad(DAY, [BreakdownItem("e", "Final", "prep", 2.5)])
    blocks, unplaced = plan_prep([day], [work], NEW_YORK)
    assert [(b.start, b.end) for b in blocks] == [(23.0, 25.5)]
    assert unplaced == 0


def test_demo_prep_is_fully_placed_without_overlaps(
    demo_events: list[Event], demo_classes: dict[str, Classification]
) -> None:
    days = compute_daily_load(demo_events, demo_classes, SEMESTER_START, SEMESTER_END)
    blocks, unplaced = plan_prep(days, demo_events, NEW_YORK)
    assert unplaced == 0
    assert sum(b.end - b.start for b in blocks) == pytest.approx(
        sum(d.prep_hours for d in days), abs=0.25 * len(blocks)
    )
    for day in {b.date for b in blocks}:
        mine = sorted((b.start, b.end) for b in blocks if b.date == day)
        others = [
            (e.start.hour + e.start.minute / 60, e.end.hour + e.end.minute / 60)
            for e in demo_events
            if e.start.date() == day and not e.all_day
        ]
        for i, (start, end) in enumerate(mine):
            assert end > start
            if i:
                assert start >= mine[i - 1][1]
            assert all(end <= s or start >= e for s, e in others)


def test_analysis_json_carries_events_and_blocks(demo_events: list[Event]) -> None:
    result = analyze(
        demo_events, SEMESTER_START, SEMESTER_END, "America/New_York", log=lambda _: None
    )
    data = analysis_json(result)
    assert data["meta"]["classifier"] == "keywords"
    assert len(data["events"]) == len(demo_events)
    assert set(data["events"][0]) == {
        "id",
        "title",
        "start",
        "end",
        "all_day",
        "type",
        "prep_hours",
        "stress",
    }
    assert data["prep_blocks"] and data["hell_weeks"][0]["report"]["source"] == "template"
    assert "Science Hall" not in str(data)  # no locations leave the backend
