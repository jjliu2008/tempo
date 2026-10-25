"""Generate demo_semester.ics: a fictional fall 2026 semester with a brutal week 9.

Run from backend/:  python -m hellweek.make_demo --out demo/demo_semester.ics

Semester weeks start on Monday; week 1 is Aug 24-30, so week 9 is Oct 19-25.
Titles avoid the classifier keywords (exam, midterm, project, due, quiz, ...)
unless the event really is one, so the keyword fallback scores it correctly.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import icalendar

TZ = ZoneInfo("America/New_York")
SEMESTER_START = date(2026, 8, 25)
LAST_CLASS_DAY = date(2026, 12, 9)
WEEK_9_START = date(2026, 10, 19)
NO_CLASS_DAYS = (
    date(2026, 9, 7),  # Labor Day
    date(2026, 10, 12),  # Fall break
    date(2026, 10, 13),
    date(2026, 11, 25),  # Thanksgiving break
    date(2026, 11, 26),
    date(2026, 11, 27),
)
DTSTAMP = datetime(2026, 8, 1, tzinfo=UTC)
WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}

HM = tuple[int, int]


def at(day: date, hm: HM) -> datetime:
    return datetime.combine(day, time(*hm), TZ)


def base_event(uid: str, summary: str, location: str = "") -> icalendar.Event:
    ev = icalendar.Event()
    ev.add("uid", f"{uid}@hellweek-demo")
    ev.add("dtstamp", DTSTAMP)
    ev.add("summary", summary)
    if location:
        ev.add("location", location)
    return ev


def timed(
    uid: str, summary: str, day: date, start: HM, end: HM, location: str = ""
) -> icalendar.Event:
    ev = base_event(uid, summary, location)
    ev.add("dtstart", at(day, start))
    ev.add("dtend", at(day, end))
    return ev


def all_day(uid: str, summary: str, day: date) -> icalendar.Event:
    ev = base_event(uid, summary)
    ev.add("dtstart", day)
    ev.add("dtend", day + timedelta(days=1))
    return ev


def first_matching_day(start: date, byday: Sequence[str]) -> date:
    wanted = {WEEKDAYS[d] for d in byday}
    day = start
    while day.weekday() not in wanted:
        day += timedelta(days=1)
    return day


def weekly(
    uid: str,
    summary: str,
    byday: Sequence[str],
    start: HM,
    end: HM,
    location: str = "",
    skip: Sequence[date] = NO_CLASS_DAYS,
) -> icalendar.Event:
    """A weekly series from the semester start through the last class day."""
    first = first_matching_day(SEMESTER_START, byday)
    ev = timed(uid, summary, first, start, end, location)
    until = at(LAST_CLASS_DAY, (23, 59)).astimezone(UTC)
    ev.add("rrule", {"freq": "weekly", "byday": list(byday), "until": until})
    wanted = {WEEKDAYS[d] for d in byday}
    exdates = [at(d, start) for d in skip if d.weekday() in wanted]
    if exdates:
        ev.add("exdate", exdates)
    return ev


def recurring_events() -> list[icalendar.Event]:
    return [
        weekly(
            "chem210",
            "CHEM 210 Organic Chemistry",
            ["MO", "WE", "FR"],
            (9, 0),
            (9, 50),
            "Science Hall 101",
        ),
        weekly(
            "math241",
            "MATH 241 Linear Algebra",
            ["MO", "WE", "FR"],
            (11, 0),
            (11, 50),
            "Math Building 214",
        ),
        weekly(
            "cs220", "CS 220 Data Structures", ["TU", "TH"], (10, 0), (11, 15), "Engineering 120"
        ),
        weekly("hist105", "HIST 105 Modern World", ["TU", "TH"], (14, 0), (15, 15), "Humanities 3"),
        weekly(
            "robotics",
            "Robotics Club meeting",
            ["WE"],
            (19, 0),
            (20, 30),
            "Makerspace",
            skip=[date(2026, 11, 25)],
        ),
        weekly(
            "cafe",
            "Campus cafe shift",
            ["SA"],
            (10, 0),
            (17, 0),
            "Bean There Cafe",
            skip=[date(2026, 11, 28)],
        ),
    ]


def social_events() -> list[icalendar.Event]:
    return [
        timed("soc-welcome", "Welcome week BBQ", date(2026, 8, 28), (17, 0), (20, 0)),
        timed("soc-football1", "Home football game", date(2026, 9, 12), (19, 0), (22, 0)),
        timed("soc-movie", "Movie night with roommates", date(2026, 9, 19), (20, 0), (23, 0)),
        timed("soc-hike", "Hiking trip", date(2026, 10, 4), (8, 0), (14, 0)),
        timed("soc-bday", "Sam's birthday dinner", date(2026, 10, 17), (18, 30), (21, 30)),
        timed("soc-halloween", "Halloween party", date(2026, 10, 31), (21, 0), (23, 59)),
        timed("soc-football2", "Away game watch party", date(2026, 11, 7), (15, 0), (18, 0)),
        all_day("soc-thanksgiving", "Thanksgiving at home", date(2026, 11, 26)),
        timed("soc-concert", "Winter concert", date(2026, 12, 5), (19, 30), (21, 30)),
    ]


def quizzes() -> list[icalendar.Event]:
    def online(uid: str, summary: str, day: date) -> icalendar.Event:
        return timed(uid, summary, day, (20, 0), (20, 30), "Online")

    return [
        online("quiz-chem1", "CHEM 210 Quiz 1", date(2026, 9, 9)),
        online("quiz-math1", "MATH 241 Quiz 1", date(2026, 9, 16)),
        online("quiz-cs1", "CS 220 Quiz 1", date(2026, 10, 1)),
        online("quiz-chem2", "CHEM 210 Quiz 2", date(2026, 10, 7)),
        online("quiz-cs2", "CS 220 Quiz 2", date(2026, 10, 19)),
        online("quiz-math2", "MATH 241 Quiz 2", date(2026, 11, 11)),
        online("quiz-chem3", "CHEM 210 Quiz 3", date(2026, 12, 2)),
    ]


def milestones() -> list[icalendar.Event]:
    """Isolated high-stress events outside week 9: one each, so no other week
    should have the two stress >= 7 events a hell week needs."""
    return [
        all_day("hist-essay", "HIST 105 essay due", date(2026, 9, 25)),
        timed(
            "hist-midterm",
            "HIST 105 Midterm",
            date(2026, 11, 19),
            (14, 0),
            (15, 15),
            "Humanities 3",
        ),
    ]


def week_9() -> list[icalendar.Event]:
    """Two midterms and a project deadline inside 48 hours (Tue 19:00 - Thu)."""
    mon, tue, wed, thu = (WEEK_9_START + timedelta(days=i) for i in range(4))
    return [
        timed(
            "chem-review", "CHEM 210 review session (TA)", mon, (18, 0), (20, 0), "Science Hall 101"
        ),
        timed("cs-sync", "CS 220 team sync", mon, (20, 30), (22, 0), "Library room 4B"),
        timed("chem-midterm", "CHEM 210 Midterm 1", tue, (19, 0), (21, 0), "Science Hall 101"),
        timed("math-midterm", "MATH 241 Midterm", wed, (16, 0), (18, 0), "Math Building 214"),
        all_day("cs-project", "CS 220 Project 2 due", thu),
    ]


def build_calendar() -> icalendar.Calendar:
    cal = icalendar.Calendar()
    cal.add("prodid", "-//Hell Week Detector//demo semester//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Demo Fall 2026 (fictional)")
    for ev in recurring_events() + social_events() + quizzes() + milestones() + week_9():
        cal.add_component(ev)
    cal.add_missing_timezones()
    return cal


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("demo_semester.ics"))
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(build_calendar().to_ical())
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
