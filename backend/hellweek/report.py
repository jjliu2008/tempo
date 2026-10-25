"""Hell week "weather report": the facts we hand Gemma, a template fallback,
and validation of what comes back. No network here."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from hellweek.classify import Classification
from hellweek.detect import HellWeek
from hellweek.load import DayLoad
from hellweek.parse import Event

MAX_OTHER_EVENTS = 12
MOVABLE_TYPES = frozenset({"social", "work", "meeting", "other"})


def short_date(day: date) -> str:
    return f"{day:%a %b} {day.day}"


def prep_starts(days: Sequence[DayLoad]) -> dict[str, date]:
    """Earliest day each event's spread prep lands on."""
    starts: dict[str, date] = {}
    for day in days:
        for item in day.breakdown:
            if item.kind == "prep":
                starts.setdefault(item.event_id, day.date)
    return starts


def report_facts(
    week: HellWeek,
    days: Sequence[DayLoad],
    events: Sequence[Event],
    classifications: Mapping[str, Classification],
    median_weekly_hours: float,
) -> dict[str, Any]:
    """Everything the forecast may mention. Titles, dates and our own numbers
    only; no locations or descriptions."""
    starts = prep_starts(days)
    key_ids = {k.event_id for k in week.key_events}
    span = [d for d in days if week.start <= d.date <= week.end]
    others = [
        e
        for e in events
        if week.start <= e.start.date() <= week.end
        and e.id not in key_ids
        and classifications[e.id].type in MOVABLE_TYPES
    ]
    return {
        "hell_week": {
            "start": short_date(week.start),
            "end": short_date(week.end),
            "busiest_7_days": f"{short_date(week.peak.start)} to {short_date(week.peak.end)}",
            "hours_in_busiest_7_days": round(week.peak.total_hours, 1),
            "normal_week_hours": round(median_weekly_hours, 1),
        },
        "high_stakes_events": [
            {
                "title": k.title,
                "type": k.type,
                "date": short_date(k.date),
                "prep_hours": k.prep_hours,
                "prep_starts": short_date(starts.get(k.event_id, k.date)),
            }
            for k in week.key_events
        ],
        "other_events": [
            {
                "title": e.title,
                "date": short_date(e.start.date()),
                "hours": round(e.duration_hours, 1),
            }
            for e in others[:MAX_OTHER_EVENTS]
        ],
        "daily_hours": {short_date(d.date): round(d.total_hours, 1) for d in span},
    }


def template_report(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Plain report from the same facts, used when Gemma is off or fails."""
    week = facts["hell_week"]
    key = facts["high_stakes_events"]
    ratio = week["hours_in_busiest_7_days"] / max(week["normal_week_hours"], 1.0)
    return {
        "headline": f"☠️ HELL WEEK: {week['start']} – {week['end']}",
        "forecast": (
            f"{week['hours_in_busiest_7_days']:.0f} hours of work from {week['busiest_7_days']}, "
            f"about {ratio:.1f}x a normal week, with {len(key)} high-stakes events."
        ),
        "advisories": [
            f"Start {k['title']} prep by {k['prep_starts']} ({k['prep_hours']:g}h)." for k in key
        ][:4],
        "source": "template",
    }


def validate_report(raw: Any) -> dict[str, Any] | None:
    """Gemma's report if it has the expected shape, trimmed; else None."""
    if not isinstance(raw, Mapping):
        return None
    headline, forecast, advisories = raw.get("headline"), raw.get("forecast"), raw.get("advisories")
    if not (isinstance(headline, str) and headline.strip()):
        return None
    if not (isinstance(forecast, str) and forecast.strip()):
        return None
    if not isinstance(advisories, list):
        return None
    tips = [a.strip() for a in advisories if isinstance(a, str) and a.strip()]
    if not tips:
        return None
    return {
        "headline": headline.strip()[:120],
        "forecast": forecast.strip()[:500],
        "advisories": [t[:240] for t in tips[:5]],
        "source": "gemma",
    }
