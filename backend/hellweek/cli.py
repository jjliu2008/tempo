"""Command line: `python -m hellweek analyze|events ...`."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from hellweek.classify import Classification, classify_events, read_classifications
from hellweek.detect import DEFAULT_HELL_HOURS, detect_hell_weeks
from hellweek.load import compute_daily_load
from hellweek.output import load_json
from hellweek.parse import (
    CalendarSourceError,
    Event,
    calendar_timezone,
    expand_events,
    looks_like_url,
    read_calendar,
)

URL_ENV_VAR = "HELLWEEK_CALENDAR_URL"


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def iso_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a YYYY-MM-DD date: {text!r}") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m hellweek", description="Hell Week Detector")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "calendar",
        nargs="?",
        help=(
            f".ics file path or http(s)/webcal URL. Private URLs are passwords: leave this "
            f"out to read ${URL_ENV_VAR} or be prompted, so the URL stays out of shell history"
        ),
    )
    common.add_argument("--start", type=iso_date, required=True)
    common.add_argument("--end", type=iso_date, required=True)
    common.add_argument(
        "--tz", help="IANA zone, e.g. America/New_York (default: the calendar's own, else UTC)"
    )
    common.add_argument("--out", default="-", help="output file (default: stdout)")

    analyze = sub.add_parser("analyze", parents=[common], help="daily load + hell weeks")
    analyze.add_argument("--classifications", type=Path, help="classes.json from the model")
    analyze.add_argument("--hell-hours", type=float, default=DEFAULT_HELL_HOURS)

    sub.add_parser("events", parents=[common], help="dump events for the classifier model")
    return parser


def calendar_source(arg: str | None) -> str:
    """The positional argument, else the env var, else a hidden prompt."""
    if arg:
        return arg
    from_env = os.environ.get(URL_ENV_VAR, "").strip()
    if from_env:
        return from_env
    if sys.stdin.isatty():
        return getpass.getpass("Paste the calendar's secret iCal address (hidden): ").strip()
    raise CalendarSourceError(f"no calendar given: pass a path, or set {URL_ENV_VAR}")


def load_events(args: argparse.Namespace) -> tuple[list[Event], str]:
    args.calendar = calendar_source(args.calendar)
    cal = read_calendar(args.calendar)
    tz_name = args.tz or calendar_timezone(cal)
    if tz_name is None:
        warn("calendar names no timezone and --tz not given; using UTC")
        tz_name = "UTC"
    return expand_events(cal, args.start, args.end, ZoneInfo(tz_name)), tz_name


def load_classifications(path: Path | None, events: Sequence[Event]) -> dict[str, Classification]:
    if path is None:
        return classify_events(events)
    overrides, skipped = read_classifications(path)
    if skipped:
        warn(f"{len(skipped)} malformed entries in {path} use keyword fallback: {skipped[:5]}")
    ids = {e.id for e in events}
    unknown = [i for i in overrides if i not in ids]
    if unknown:
        warn(f"{len(unknown)} ids in {path} match no event in range: {unknown[:5]}")
    return classify_events(events, overrides)


def write_json(data: Any, out: str) -> None:
    if out == "-":
        json.dump(data, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path}", file=sys.stderr)


def run(args: argparse.Namespace) -> None:
    events, tz_name = load_events(args)
    if args.command == "events":
        write_json([e.to_dict() for e in events], args.out)
        return
    classifications = load_classifications(args.classifications, events)
    days = compute_daily_load(events, classifications, args.start, args.end)
    detection = detect_hell_weeks(days, events, classifications, args.hell_hours)
    write_json(load_json(days, detection, tz_name), args.out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.start > args.end:
        parser.error("--start must be on or before --end")
    try:
        run(args)
    except CalendarSourceError as exc:
        parser.error(str(exc))
    except ZoneInfoNotFoundError:
        parser.error(f"unknown timezone: {args.tz}")
    except OSError as exc:
        if exc.filename is not None and looks_like_url(str(exc.filename)):
            # Never echo it: it may be a secret address with a mangled https:// prefix.
            parser.error("could not read the calendar; URLs must start with https:// or webcal://")
        if isinstance(exc, FileNotFoundError):
            parser.error(f"file not found: {exc.filename}")
        parser.error(str(exc))
    except ValueError as exc:
        parser.error(str(exc))
    return 0
