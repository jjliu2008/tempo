import pytest

from hellweek.classify import (
    FALLBACK,
    Classification,
    classify_events,
    keyword_classify,
    parse_classifications,
)
from hellweek.parse import Event


@pytest.mark.parametrize(
    ("title", "expected_type"),
    [
        ("CHEM 210 Midterm 1", "exam"),
        ("Final exam", "exam"),
        ("Finals week", "exam"),
        ("Final project due", "deadline"),
        ("Lab report submission", "deadline"),
        ("CS 220 Quiz 2", "quiz"),
        ("Dueling club", "other"),
        ("Examine the samples", "other"),
        ("Robotics Club meeting", "other"),
    ],
)
def test_keyword_rules(title: str, expected_type: str) -> None:
    assert keyword_classify(title).type == expected_type


def test_keyword_rule_values_match_spec() -> None:
    assert keyword_classify("Midterm") == Classification("exam", 10.0, 9)
    assert keyword_classify("Project due") == Classification("deadline", 6.0, 7)
    assert keyword_classify("Quiz") == Classification("quiz", 2.0, 4)
    assert keyword_classify("Lunch") == FALLBACK == Classification("other", 0.0, 1)


def test_parse_classifications_keeps_good_and_reports_bad() -> None:
    good, bad = parse_classifications(
        {
            "a": {"type": "exam", "prep_hours": 8, "stress": 7},
            "b": {"type": "DEADLINE", "prep_hours": "3.5", "stress": 12},
            "c": {"type": "party", "prep_hours": 0, "stress": 2},
            "d": {"type": "exam", "prep_hours": -1, "stress": 5},
            "e": {"type": "exam"},
            "f": "exam",
        }
    )
    assert good == {
        "a": Classification("exam", 8.0, 7),
        "b": Classification("deadline", 3.5, 10),
    }
    assert sorted(bad) == ["c", "d", "e", "f"]


def test_parse_classifications_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        parse_classifications([{"type": "exam"}])


def test_model_overrides_win_and_missing_events_fall_back(demo_events: list[Event]) -> None:
    midterm = next(e for e in demo_events if e.title == "CHEM 210 Midterm 1")
    override = Classification("exam", 3.0, 5)
    classes = classify_events(demo_events, {midterm.id: override})
    assert classes[midterm.id] == override
    quiz = next(e for e in demo_events if e.title == "CS 220 Quiz 2")
    assert classes[quiz.id] == keyword_classify(quiz.title)
