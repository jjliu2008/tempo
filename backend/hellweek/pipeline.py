"""The whole analysis in one call, shared by the CLI and the web API:
classify -> daily load -> hell weeks -> forecasts -> study blocks -> JSON."""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hellweek.classify import Classification, classify_events
from hellweek.detect import DEFAULT_HELL_HOURS, Detection, detect_hell_weeks
from hellweek.gemma import GemmaClient, gemma_classify_events, gemma_report
from hellweek.load import DayLoad, compute_daily_load
from hellweek.output import ROUND, load_json
from hellweek.parse import Event
from hellweek.plan import PrepBlock, plan_prep
from hellweek.report import report_facts, template_report

Log = Callable[[str], None]


def stderr_log(message: str) -> None:
    print(message, file=sys.stderr)


@dataclass(frozen=True)
class Analysis:
    events: list[Event]
    classifications: dict[str, Classification]
    days: list[DayLoad]
    detection: Detection
    reports: list[dict[str, Any]]
    prep_blocks: list[PrepBlock]
    unplaced_prep_hours: float
    tz_name: str
    classifier: str


def gemma_classifications(
    events: Sequence[Event], client: GemmaClient, cache: Path | None, log: Log
) -> dict[str, Classification]:
    titles = len({e.title.strip() for e in events})
    log(f"Gemma: estimating prep for {titles} unique titles...")
    result = gemma_classify_events(events, client, cache)
    for error in result.errors:
        log(f"warning: Gemma batch failed, those titles use keyword rules: {error}")
    log(
        f"Gemma: {result.from_gemma} titles from the API, {result.from_cache} cached, "
        f"{len(result.missing_titles)} on keyword fallback"
    )
    return result.by_event_id


def analyze(
    events: list[Event],
    start: date,
    end: date,
    tz_name: str,
    *,
    overrides: Mapping[str, Classification] | None = None,
    gemma: GemmaClient | None = None,
    gemma_cache: Path | None = None,
    hell_hours: float = DEFAULT_HELL_HOURS,
    log: Log = stderr_log,
) -> Analysis:
    """Precedence for each event: `overrides` (classes.json), then Gemma, then keywords."""
    from_gemma = gemma_classifications(events, gemma, gemma_cache, log) if gemma else {}
    classifications = classify_events(events, {**from_gemma, **(overrides or {})})
    days = compute_daily_load(events, classifications, start, end)
    detection = detect_hell_weeks(days, events, classifications, hell_hours)
    reports = []
    for week in detection.hell_weeks:
        facts = report_facts(week, days, events, classifications, detection.median_weekly_hours)
        written = gemma_report(facts, gemma) if gemma else None
        reports.append(written or template_report(facts))
    blocks, unplaced = plan_prep(days, events, ZoneInfo(tz_name))
    return Analysis(
        events=events,
        classifications=classifications,
        days=days,
        detection=detection,
        reports=reports,
        prep_blocks=blocks,
        unplaced_prep_hours=unplaced,
        tz_name=tz_name,
        classifier="gemma" if from_gemma else "keywords",
    )


def analysis_json(a: Analysis) -> dict[str, Any]:
    """load.json: meta, days and hell_weeks (see output.py), plus the classified
    events and study blocks a timeline view needs. No locations or descriptions."""
    data = load_json(a.days, a.detection, a.tz_name, a.reports)
    data["meta"]["classifier"] = a.classifier
    data["meta"]["unplaced_prep_hours"] = round(a.unplaced_prep_hours, ROUND)
    data["events"] = [
        {
            "id": e.id,
            "title": e.title,
            "start": e.start.isoformat(),
            "end": e.end.isoformat(),
            "all_day": e.all_day,
            "type": a.classifications[e.id].type,
            "prep_hours": a.classifications[e.id].prep_hours,
            "stress": a.classifications[e.id].stress,
        }
        for e in a.events
    ]
    data["prep_blocks"] = [
        {
            "event_id": b.event_id,
            "title": b.title,
            "date": b.date.isoformat(),
            "start_hour": b.start,
            "end_hour": b.end,
        }
        for b in a.prep_blocks
    ]
    return data
