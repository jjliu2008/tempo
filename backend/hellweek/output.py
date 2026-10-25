"""Shape results into the JSON the frontend reads (load.json)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from hellweek.detect import Detection, HellWeek
from hellweek.load import DayLoad

ROUND = 2


def day_json(day: DayLoad) -> dict[str, Any]:
    scheduled = round(day.scheduled_hours, ROUND)
    prep = round(day.prep_hours, ROUND)
    # Scheduled items first, then prep; each in event order.
    items = sorted(day.breakdown, key=lambda b: b.kind != "scheduled")
    return {
        "date": day.date.isoformat(),
        "scheduled_hours": scheduled,
        "prep_hours": prep,
        # Sum of the rounded parts, so the numbers the frontend shows add up.
        "total_hours": round(scheduled + prep, ROUND),
        "breakdown": [
            {
                "event_id": b.event_id,
                "title": b.title,
                "kind": b.kind,
                "hours": round(b.hours, ROUND),
            }
            for b in items
        ],
    }


def hell_week_json(week: HellWeek) -> dict[str, Any]:
    return {
        "start": week.start.isoformat(),
        "end": week.end.isoformat(),
        "total_hours": round(week.total_hours, ROUND),
        "peak_start": week.peak.start.isoformat(),
        "peak_end": week.peak.end.isoformat(),
        "peak_hours": round(week.peak.total_hours, ROUND),
        "key_events": [
            {
                "event_id": k.event_id,
                "title": k.title,
                "type": k.type,
                "date": k.date.isoformat(),
                "prep_hours": k.prep_hours,
                "stress": k.stress,
            }
            for k in week.key_events
        ],
    }


def load_json(days: Sequence[DayLoad], detection: Detection, tz: str) -> dict[str, Any]:
    return {
        "meta": {
            "start": days[0].date.isoformat() if days else None,
            "end": days[-1].date.isoformat() if days else None,
            "timezone": tz,
            "threshold_hours": round(detection.threshold, ROUND),
            "median_weekly_hours": round(detection.median_weekly_hours, ROUND),
        },
        "days": [day_json(d) for d in days],
        "hell_weeks": [hell_week_json(h) for h in detection.hell_weeks],
    }
