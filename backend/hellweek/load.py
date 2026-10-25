"""Daily load: scheduled hours plus prep hours spread over the days before each event."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from hellweek.classify import Classification
from hellweek.parse import Event

LEAD_DAYS = {"exam": 4, "deadline": 5, "quiz": 2}
DEFAULT_LEAD_DAYS = 3


@dataclass(frozen=True)
class BreakdownItem:
    event_id: str
    title: str
    kind: Literal["scheduled", "prep"]
    hours: float


@dataclass
class DayLoad:
    date: date
    breakdown: list[BreakdownItem] = field(default_factory=list)

    @property
    def scheduled_hours(self) -> float:
        return sum(b.hours for b in self.breakdown if b.kind == "scheduled")

    @property
    def prep_hours(self) -> float:
        return sum(b.hours for b in self.breakdown if b.kind == "prep")

    @property
    def total_hours(self) -> float:
        return self.scheduled_hours + self.prep_hours


def date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def lead_days(event_type: str) -> int:
    return LEAD_DAYS.get(event_type, DEFAULT_LEAD_DAYS)


def spread_prep(
    event_day: date, prep_hours: float, lead: int, start: date, end: date
) -> dict[date, float]:
    """Spread prep over the `lead` days before event_day with a linear ramp.

    Day k before the event gets weight lead - k + 1, so the day before gets the
    most. Days outside [start, end] are dropped and the rest renormalized, so
    the total is preserved. If no lead day survives (event on the first day),
    all prep lands on the event day. Events outside the range get no prep.
    """
    if prep_hours <= 0 or not start <= event_day <= end:
        return {}
    weights = {
        event_day - timedelta(days=k): float(lead - k + 1)
        for k in range(1, lead + 1)
        if start <= event_day - timedelta(days=k) <= end
    }
    if not weights:
        return {event_day: prep_hours}
    total = sum(weights.values())
    return {day: prep_hours * w / total for day, w in sorted(weights.items())}


def split_by_day(start: datetime, end: datetime) -> dict[date, float]:
    """Elapsed hours of [start, end) that fall on each local calendar day."""
    hours: dict[date, float] = {}
    cursor = start
    while cursor < end:
        midnight = datetime.combine(cursor.date() + timedelta(days=1), time(), cursor.tzinfo)
        chunk_end = min(end, midnight)
        elapsed = chunk_end.astimezone(UTC) - cursor.astimezone(UTC)
        hours[cursor.date()] = hours.get(cursor.date(), 0.0) + elapsed.total_seconds() / 3600
        cursor = chunk_end
    return hours


def compute_daily_load(
    events: Iterable[Event],
    classifications: Mapping[str, Classification],
    start: date,
    end: date,
) -> list[DayLoad]:
    """One DayLoad for every day in [start, end], including empty days."""
    days = {d: DayLoad(d) for d in date_range(start, end)}
    for event in events:
        if not event.all_day:
            for day, hours in split_by_day(event.start, event.end).items():
                if day in days and hours > 0:
                    days[day].breakdown.append(
                        BreakdownItem(event.id, event.title, "scheduled", hours)
                    )
        c = classifications[event.id]
        for day, hours in spread_prep(
            event.start.date(), c.prep_hours, lead_days(c.type), start, end
        ).items():
            days[day].breakdown.append(BreakdownItem(event.id, event.title, "prep", hours))
    return list(days.values())
