"""Place each day's spread prep hours into that day's free time as study blocks,
so a timeline view shows the hidden work, not just the scheduled events.

Hours are local wall-clock hours from the day's midnight; values past 24 are
after midnight, which the heat map draws under the evening they belong to.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from hellweek.load import DayLoad
from hellweek.parse import Event

STUDY_START = 9.0
STUDY_END = 26.0  # a packed day spills prep into late night (2am)
SLOT = 0.25
MIN_GAP = 0.5  # shorter gaps (walking between classes) are not study time

Interval = tuple[float, float]


@dataclass(frozen=True)
class PrepBlock:
    event_id: str  # the exam or deadline this prep is for
    title: str
    date: date
    start: float
    end: float


def wall_hours(moment: datetime, midnight: datetime) -> float:
    """Wall-clock hours since midnight (the grid's clock, so DST days stay aligned)."""
    local = moment.astimezone(midnight.tzinfo).replace(tzinfo=None)
    return (local - midnight.replace(tzinfo=None)).total_seconds() / 3600


def busy_intervals(events: Sequence[Event], day: date, tz: ZoneInfo) -> list[Interval]:
    midnight = datetime.combine(day, time(), tz)
    busy = []
    for e in events:
        if e.all_day:
            continue
        start, end = wall_hours(e.start, midnight), wall_hours(e.end, midnight)
        if end > 0 and start < STUDY_END:
            busy.append((max(0.0, start), min(STUDY_END, end)))
    return busy


def free_intervals(busy: Sequence[Interval], lo: float, hi: float) -> list[Interval]:
    free = []
    cursor = lo
    for start, end in sorted(busy):
        if start > cursor:
            free.append((cursor, min(start, hi)))
        cursor = max(cursor, end)
        if cursor >= hi:
            break
    if cursor < hi:
        free.append((cursor, hi))
    aligned = [(math.ceil(a / SLOT) * SLOT, math.floor(b / SLOT) * SLOT) for a, b in free]
    return [(a, b) for a, b in aligned if b - a >= MIN_GAP]


def snap(hours: float) -> float:
    """Round to the grid's quarter hours, keeping any real prep visible."""
    return max(SLOT, round(hours / SLOT) * SLOT) if hours > 0 else 0.0


def fill(
    items: Sequence[tuple[str, str, float]], free: list[Interval], day: date
) -> tuple[list[PrepBlock], float]:
    """Fill free time in order with (event_id, title, hours); returns blocks and
    the hours that did not fit."""
    blocks: list[PrepBlock] = []
    unplaced = 0.0
    slots = list(free)
    for event_id, title, hours in items:
        need = snap(hours)
        while need > 0 and slots:
            start, end = slots[0]
            take = min(need, end - start)
            blocks.append(PrepBlock(event_id, title, day, start, start + take))
            need -= take
            if start + take >= end - 1e-9:
                slots.pop(0)
            else:
                slots[0] = (start + take, end)
        unplaced += need
    return blocks, unplaced


def plan_prep(
    days: Sequence[DayLoad], events: Sequence[Event], tz: ZoneInfo
) -> tuple[list[PrepBlock], float]:
    """Study blocks for every day's prep, plus total hours that found no free time."""
    blocks: list[PrepBlock] = []
    unplaced = 0.0
    for day in days:
        items = [(b.event_id, b.title, b.hours) for b in day.breakdown if b.kind == "prep"]
        if not items:
            continue
        free = free_intervals(busy_intervals(events, day.date, tz), STUDY_START, STUDY_END)
        placed, missing = fill(items, free, day.date)
        blocks.extend(placed)
        unplaced += missing
    return blocks, unplaced
