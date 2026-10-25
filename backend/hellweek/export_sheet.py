"""Export the fictional demo semester as spreadsheets for slides and demos.

Run from backend/:  python -m hellweek.export_sheet --out-dir demo

Writes three CSVs (open in Excel, Numbers or Google Sheets):
  demo_events.csv       every event with its type, prep hours and stress
  demo_daily_load.csv   scheduled + prep hours per day, and whether it is in a hell week
  demo_hell_weeks.csv   the detected hell weeks and their forecast

Uses the keyword classifier, so the numbers are deterministic and need no API key.
Every event is fictional (see make_demo.py).
"""

from __future__ import annotations

import argparse
import csv
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from hellweek.make_demo import build_calendar
from hellweek.parse import expand_events
from hellweek.pipeline import Analysis, analyze

TZ_NAME = "America/New_York"
START, END = date(2026, 8, 25), date(2026, 12, 15)


def demo_analysis() -> Analysis:
    tz = ZoneInfo(TZ_NAME)
    events = sorted(expand_events(build_calendar(), START, END, tz), key=lambda e: (e.start, e.id))
    return analyze(events, START, END, TZ_NAME, log=lambda message: None)


def write_csv(path: Path, header: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def event_rows(a: Analysis) -> list[list[object]]:
    rows: list[list[object]] = []
    for e in a.events:
        c = a.classifications[e.id]
        rows.append(
            [
                e.start.date().isoformat(),
                f"{e.start:%a}",
                "all day" if e.all_day else f"{e.start:%H:%M}",
                "" if e.all_day else f"{e.end:%H:%M}",
                round(e.duration_hours, 2),
                e.title,
                c.type,
                c.prep_hours,
                c.stress,
            ]
        )
    return rows


def day_rows(a: Analysis) -> list[list[object]]:
    in_hell = {d.date for d in a.days for w in a.detection.hell_weeks if w.start <= d.date <= w.end}
    return [
        [
            d.date.isoformat(),
            f"{d.date:%a}",
            round(d.scheduled_hours, 2),
            round(d.prep_hours, 2),
            round(d.total_hours, 2),
            "yes" if d.date in in_hell else "",
        ]
        for d in a.days
    ]


def hell_week_rows(a: Analysis) -> list[list[object]]:
    rows: list[list[object]] = []
    for week, report in zip(a.detection.hell_weeks, a.reports, strict=False):
        rows.append(
            [
                week.start.isoformat(),
                week.end.isoformat(),
                round(week.peak.total_hours, 1),
                round(a.detection.median_weekly_hours, 1),
                "; ".join(k.title for k in week.key_events),
                report["headline"],
                report["forecast"],
            ]
        )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out-dir", type=Path, default=Path("demo"))
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    a = demo_analysis()
    write_csv(
        args.out_dir / "demo_events.csv",
        ["date", "weekday", "start", "end", "hours", "title", "type", "prep_hours", "stress"],
        event_rows(a),
    )
    write_csv(
        args.out_dir / "demo_daily_load.csv",
        ["date", "weekday", "scheduled_hours", "prep_hours", "total_hours", "in_hell_week"],
        day_rows(a),
    )
    write_csv(
        args.out_dir / "demo_hell_weeks.csv",
        [
            "start",
            "end",
            "peak_7_day_hours",
            "normal_week_hours",
            "key_events",
            "headline",
            "forecast",
        ],
        hell_week_rows(a),
    )
    print(f"wrote 3 sheets to {args.out_dir}/ ({len(a.events)} events)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
