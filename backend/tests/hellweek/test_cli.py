import json
from pathlib import Path

import pytest

from hellweek.cli import main
from hellweek.make_demo import build_calendar

from .conftest import SEMESTER_END, SEMESTER_START

RANGE = ["--start", SEMESTER_START.isoformat(), "--end", SEMESTER_END.isoformat()]


@pytest.fixture
def demo_ics(tmp_path: Path) -> Path:
    path = tmp_path / "demo.ics"
    path.write_bytes(build_calendar().to_ical())
    return path


def test_analyze_writes_frontend_json(demo_ics: Path, tmp_path: Path) -> None:
    out = tmp_path / "load.json"
    assert main(["analyze", str(demo_ics), *RANGE, "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["meta"]["timezone"] == "America/New_York"
    assert len(data["days"]) == (SEMESTER_END - SEMESTER_START).days + 1
    for day in data["days"]:
        assert day["total_hours"] == round(day["scheduled_hours"] + day["prep_hours"], 2)
        assert {b["kind"] for b in day["breakdown"]} <= {"scheduled", "prep"}
    (week,) = data["hell_weeks"]
    assert week["start"] <= "2026-10-25" and week["end"] >= "2026-10-19"
    assert {k["type"] for k in week["key_events"]} == {"exam", "deadline"}


def test_events_ids_round_trip_into_classifications(demo_ics: Path, tmp_path: Path) -> None:
    events_path, classes_path, out = (tmp_path / n for n in ("e.json", "c.json", "l.json"))
    main(["events", str(demo_ics), *RANGE, "--out", str(events_path)])
    events = json.loads(events_path.read_text(encoding="utf-8"))
    midterm = next(e for e in events if e["title"] == "CHEM 210 Midterm 1")
    classes = {midterm["id"]: {"type": "exam", "prep_hours": 1, "stress": 2}}
    classes_path.write_text(json.dumps(classes), encoding="utf-8")

    main(
        [
            "analyze",
            str(demo_ics),
            *RANGE,
            "--classifications",
            str(classes_path),
            "--out",
            str(out),
        ]
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    prep_items = [
        b
        for d in data["days"]
        for b in d["breakdown"]
        if b["event_id"] == midterm["id"] and b["kind"] == "prep"
    ]
    assert sum(b["hours"] for b in prep_items) == pytest.approx(1.0)


def test_event_ids_do_not_depend_on_tz(demo_ics: Path, tmp_path: Path) -> None:
    ids = []
    for tz in ("America/New_York", "Asia/Tokyo"):
        out = tmp_path / f"{tz.replace('/', '_')}.json"
        main(
            [
                "events",
                str(demo_ics),
                "--start",
                "2026-10-19",
                "--end",
                "2026-10-23",
                "--tz",
                tz,
                "--out",
                str(out),
            ]
        )
        ids.append({e["id"] for e in json.loads(out.read_text(encoding="utf-8"))})
    assert ids[0] & ids[1]
    midterm_ids = [{i for i in s if i.startswith("chem-midterm")} for s in ids]
    assert midterm_ids[0] == midterm_ids[1] != set()


def test_bad_arguments_exit_with_usage_error(demo_ics: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["analyze", str(demo_ics), "--start", "2026-12-15", "--end", "2026-08-25"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit):
        main(["analyze", "missing.ics", *RANGE])
