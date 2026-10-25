"""Hell week detection: sliding 7-day windows over daily load."""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from hellweek.classify import Classification
from hellweek.load import DayLoad
from hellweek.parse import Event

WINDOW_DAYS = 7
DEFAULT_HELL_HOURS = 50.0
MEDIAN_RATIO = 1.4
HIGH_STRESS = 7
MIN_HIGH_STRESS_EVENTS = 2


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    total_hours: float
    high_stress_ids: frozenset[str]


@dataclass(frozen=True)
class KeyEvent:
    event_id: str
    title: str
    type: str
    date: date
    prep_hours: float
    stress: int


@dataclass(frozen=True)
class HellWeek:
    start: date
    end: date
    total_hours: float
    peak: Window
    key_events: list[KeyEvent]


@dataclass(frozen=True)
class Detection:
    threshold: float
    median_weekly_hours: float
    hell_weeks: list[HellWeek]


def sliding_windows(
    days: Sequence[DayLoad], high_stress_by_day: Mapping[date, set[str]], size: int = WINDOW_DAYS
) -> list[Window]:
    """Every full `size`-day window; a range shorter than that is one window."""
    starts = range(max(1, len(days) - size + 1))
    windows = []
    for i in starts:
        span = days[i : i + size]
        ids = set().union(*(high_stress_by_day.get(d.date, set()) for d in span))
        windows.append(
            Window(span[0].date, span[-1].date, sum(d.total_hours for d in span), frozenset(ids))
        )
    return windows


def load_threshold(
    windows: Sequence[Window], hell_hours: float = DEFAULT_HELL_HOURS, ratio: float = MEDIAN_RATIO
) -> tuple[float, float]:
    """(threshold, median window load). Threshold = max(hell_hours, ratio * median)."""
    median = statistics.median(w.total_hours for w in windows) if windows else 0.0
    return max(hell_hours, ratio * median), median


def is_flagged(window: Window, threshold: float) -> bool:
    return window.total_hours > threshold and len(window.high_stress_ids) >= MIN_HIGH_STRESS_EVENTS


def merge_overlapping(windows: Sequence[Window]) -> list[list[Window]]:
    """Group date-sorted windows into runs whose spans overlap."""
    groups: list[list[Window]] = []
    for w in windows:
        if groups and w.start <= groups[-1][-1].end:
            groups[-1].append(w)
        else:
            groups.append([w])
    return groups


def high_stress_by_day(
    events: Iterable[Event], classifications: Mapping[str, Classification]
) -> dict[date, set[str]]:
    by_day: dict[date, set[str]] = {}
    for e in events:
        if classifications[e.id].stress >= HIGH_STRESS:
            by_day.setdefault(e.start.date(), set()).add(e.id)
    return by_day


def build_hell_week(
    group: Sequence[Window],
    days_by_date: Mapping[date, DayLoad],
    events_by_id: Mapping[str, Event],
    classifications: Mapping[str, Classification],
) -> HellWeek:
    start, end = group[0].start, group[-1].end
    ids = frozenset().union(*(w.high_stress_ids for w in group))
    key_events = sorted(
        (
            KeyEvent(
                event_id=i,
                title=events_by_id[i].title,
                type=classifications[i].type,
                date=events_by_id[i].start.date(),
                prep_hours=classifications[i].prep_hours,
                stress=classifications[i].stress,
            )
            for i in ids
        ),
        key=lambda k: (k.date, events_by_id[k.event_id].start, k.event_id),
    )
    return HellWeek(
        start=start,
        end=end,
        total_hours=sum(d.total_hours for day, d in days_by_date.items() if start <= day <= end),
        peak=max(group, key=lambda w: (w.total_hours, len(w.high_stress_ids))),
        key_events=key_events,
    )


def detect_hell_weeks(
    days: Sequence[DayLoad],
    events: Sequence[Event],
    classifications: Mapping[str, Classification],
    hell_hours: float = DEFAULT_HELL_HOURS,
) -> Detection:
    """Flag windows over threshold with 2+ high-stress events, merge overlaps,
    and rank hell weeks by their heaviest 7-day window."""
    windows = sliding_windows(days, high_stress_by_day(events, classifications))
    threshold, median = load_threshold(windows, hell_hours)
    groups = merge_overlapping([w for w in windows if is_flagged(w, threshold)])
    days_by_date = {d.date: d for d in days}
    events_by_id = {e.id: e for e in events}
    hell_weeks = [build_hell_week(g, days_by_date, events_by_id, classifications) for g in groups]
    hell_weeks.sort(key=lambda h: h.peak.total_hours, reverse=True)
    return Detection(threshold, median, hell_weeks)
