"""Event classifications: the model's classes.json, with a keyword fallback."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hellweek.parse import Event

EVENT_TYPES = frozenset({"exam", "deadline", "quiz", "class", "meeting", "social", "work", "other"})


@dataclass(frozen=True)
class Classification:
    type: str
    prep_hours: float
    stress: int


# First match wins. Deadline words go first so "Final project due" is a
# deadline, not an exam; "Final exam" still matches the exam rule.
KEYWORD_RULES: tuple[tuple[re.Pattern[str], Classification], ...] = (
    (
        re.compile(r"\b(projects?|due|deadlines?|submissions?)\b", re.I),
        Classification("deadline", 6.0, 7),
    ),
    (re.compile(r"\b(finals?|midterms?|exams?)\b", re.I), Classification("exam", 10.0, 9)),
    (re.compile(r"\bquiz(zes)?\b", re.I), Classification("quiz", 2.0, 4)),
)
FALLBACK = Classification("other", 0.0, 1)


def keyword_classify(title: str) -> Classification:
    for pattern, classification in KEYWORD_RULES:
        if pattern.search(title):
            return classification
    return FALLBACK


def parse_entry(raw: Any) -> Classification | None:
    """Validate one classes.json entry; None if it is unusable."""
    if not isinstance(raw, Mapping):
        return None
    try:
        kind = str(raw["type"]).strip().lower()
        prep = float(raw["prep_hours"])
        stress = int(raw["stress"])
    except (KeyError, TypeError, ValueError):
        return None
    if kind not in EVENT_TYPES or prep < 0:
        return None
    return Classification(kind, prep, max(0, min(10, stress)))


def parse_classifications(data: Any) -> tuple[dict[str, Classification], list[str]]:
    """Return the usable entries and the ids of entries that were skipped."""
    if not isinstance(data, Mapping):
        raise ValueError("classes.json must be a JSON object keyed by event id")
    good: dict[str, Classification] = {}
    bad: list[str] = []
    for event_id, raw in data.items():
        entry = parse_entry(raw)
        if entry is None:
            bad.append(str(event_id))
        else:
            good[str(event_id)] = entry
    return good, bad


def read_classifications(path: str | Path) -> tuple[dict[str, Classification], list[str]]:
    return parse_classifications(json.loads(Path(path).read_text(encoding="utf-8")))


def classify_events(
    events: Iterable[Event], overrides: Mapping[str, Classification] | None = None
) -> dict[str, Classification]:
    """Model classification where present, keyword fallback otherwise."""
    overrides = overrides or {}
    return {e.id: overrides.get(e.id) or keyword_classify(e.title) for e in events}
