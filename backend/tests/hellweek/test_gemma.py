"""Gemma integration, against a fake API: nothing here touches the network."""

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

import hellweek.cli
from hellweek.classify import Classification, keyword_classify
from hellweek.gemma import (
    API_KEY_VAR,
    ApiError,
    GemmaClient,
    GemmaError,
    classify_titles,
    find_api_key,
    gemma_classify_events,
    parse_batch,
    retry_delay,
)
from hellweek.make_demo import build_calendar
from hellweek.parse import Event
from hellweek.report import template_report, validate_report

KEY = "test-key-NOT-A-REAL-KEY"
RANGE = ["--start", "2026-08-25", "--end", "2026-12-15"]

Reply = Callable[[str], Any]


def reply_json(value: Any) -> bytes:
    """A Gemini API response: a thought part (to be skipped) then the answer."""
    parts = [{"text": "thinking about it", "thought": True}, {"text": json.dumps(value)}]
    return json.dumps({"candidates": [{"content": {"parts": parts}}]}).encode()


def prompt_titles(prompt: str) -> list[str]:
    return [json.loads(m) for m in re.findall(r'^\d+\. (".*")$', prompt, re.M)]


def keyword_answers(prompt: str) -> dict[str, Any]:
    """Answer a classification prompt the way the keyword rules would."""
    answers = {}
    for i, title in enumerate(prompt_titles(prompt), 1):
        c = keyword_classify(title)
        answers[str(i)] = {"type": c.type, "prep_hours": c.prep_hours, "stress": c.stress}
    return answers


class FakeApi:
    """Plays queued replies (values or ApiErrors), then answers via `default`."""

    def __init__(self, *queued: Any, default: Reply | None = None) -> None:
        self.queued = list(queued)
        self.default = default
        self.requests: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> bytes:
        payload = json.loads(body)
        self.requests.append((url, payload, dict(headers)))
        if self.queued:
            item = self.queued.pop(0)
            if isinstance(item, ApiError):
                raise item
            return reply_json(item)
        if self.default is None:
            raise ApiError(503, "This model is currently experiencing high demand.")
        return reply_json(self.default(payload["contents"][0]["parts"][0]["text"]))

    def prompts(self) -> list[str]:
        return [p["contents"][0]["parts"][0]["text"] for _, p, _ in self.requests]


def make_client(api: FakeApi, sleeps: list[float] | None = None) -> GemmaClient:
    record = sleeps if sleeps is not None else []
    return GemmaClient(KEY, models=("model-a", "model-b"), transport=api, sleep=record.append)


def test_classifies_each_unique_title_once_and_sends_only_titles(demo_events: list[Event]) -> None:
    api = FakeApi(default=keyword_answers)
    result = gemma_classify_events(demo_events, make_client(api))

    unique = {e.title for e in demo_events}
    assert len(demo_events) > len(unique)
    assert sorted(t for p in api.prompts() for t in prompt_titles(p)) == sorted(unique)
    assert len(result.by_event_id) == len(demo_events)
    assert result.missing_titles == [] and result.errors == []
    sent = json.dumps([payload for _, payload, _ in api.requests])
    for private in ("Science Hall", "Engineering 120", "Bean There Cafe", "hellweek-demo"):
        assert private not in sent
    url, _, headers = api.requests[0]
    assert headers["x-goog-api-key"] == KEY
    assert KEY not in url


def test_titles_are_batched() -> None:
    api = FakeApi(default=keyword_answers)
    titles = [f"Event {i}" for i in range(95)] + ["Event 3", " Event 4 "]
    found, errors = classify_titles(titles, make_client(api), batch_size=40)
    assert len(api.requests) == 3
    assert len(found) == 95 and errors == []


def test_rate_limit_waits_as_asked_then_retries() -> None:
    sleeps: list[float] = []
    api = FakeApi(ApiError(429, "quota", retry_after=17), {"ok": True})
    assert make_client(api, sleeps).generate_json("hi") == {"ok": True}
    assert len(sleeps) == 1 and 17 <= sleeps[0] < 18


def test_busy_model_falls_back_to_next_model() -> None:
    api = FakeApi(*[ApiError(503, "busy")] * 4, {"ok": True})
    assert make_client(api).generate_json("hi") == {"ok": True}
    assert [url.split("/")[-1] for url, _, _ in api.requests] == ["model-a:generateContent"] * 4 + [
        "model-b:generateContent"
    ]


def test_bad_key_fails_fast_without_leaking_it() -> None:
    api = FakeApi(ApiError(403, "API key not valid"))
    with pytest.raises(GemmaError) as exc:
        make_client(api).generate_json("hi")
    assert len(api.requests) == 1
    assert KEY not in str(exc.value)


def test_gives_up_after_all_models_and_attempts() -> None:
    api = FakeApi()
    with pytest.raises(GemmaError, match="unavailable"):
        make_client(api).generate_json("hi")
    assert len(api.requests) == 8


def test_bad_json_is_retried() -> None:
    replies = [b"Sure! Here you go: {broken", json.dumps({"ok": True}).encode()]

    def transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> bytes:
        parts = [{"text": replies.pop(0).decode()}]
        return json.dumps({"candidates": [{"content": {"parts": parts}}]}).encode()

    client = GemmaClient(KEY, models=("m",), transport=transport, sleep=lambda s: None)
    assert client.generate_json("hi") == {"ok": True}
    assert replies == []


def test_parse_batch_validates_and_tolerates_shapes() -> None:
    titles = ["Midterm", "Party", "Essay due", "Lab"]
    raw = {
        "1": {"type": "exam", "prep_hours": 500, "stress": 9},
        "2": {"type": "rave", "prep_hours": 0, "stress": 2},
        "3": {"type": "deadline", "prep_hours": "6", "stress": 0},
    }
    assert parse_batch(raw, titles) == {
        "Midterm": Classification("exam", 40.0, 9),
        "Essay due": Classification("deadline", 6.0, 1),
    }
    wrapped = [{"1": {"type": "class", "prep_hours": 0, "stress": 2}}]
    assert parse_batch(wrapped, ["Lab"]) == {"Lab": Classification("class", 0.0, 2)}
    as_list = [{"type": "class", "prep_hours": 0, "stress": 2}]
    assert parse_batch(as_list, ["Lab"]) == {"Lab": Classification("class", 0.0, 2)}
    assert parse_batch("nope", titles) == {}


def test_fenced_json_is_accepted() -> None:
    def transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> bytes:
        parts = [{"text": '```json\n{"ok": true}\n```'}]
        return json.dumps({"candidates": [{"content": {"parts": parts}}]}).encode()

    assert GemmaClient(KEY, transport=transport).generate_json("hi") == {"ok": True}


def test_cache_skips_the_api_on_rerun(demo_events: list[Event], tmp_path: Path) -> None:
    cache = tmp_path / "cache.json"
    first = FakeApi(default=keyword_answers)
    gemma_classify_events(demo_events, make_client(first), cache)
    second = FakeApi()
    result = gemma_classify_events(demo_events, make_client(second), cache)
    assert second.requests == []
    assert result.from_cache == len({e.title for e in demo_events})
    assert len(result.by_event_id) == len(demo_events)


def test_retry_delay_reads_header_or_google_retry_info() -> None:
    assert retry_delay("12", b"") == 12
    body = b'{"error": {"details": [{"@type": "RetryInfo", "retryDelay": "31s"}]}}'
    assert retry_delay(None, body) == 31
    assert retry_delay(None, b"{}") is None


def test_find_api_key_prefers_env_then_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nOTHER=1\nGEMINI_API_KEY='from-file'\n", encoding="utf-8")
    assert find_api_key({}, [env_file]) == "from-file"
    assert find_api_key({API_KEY_VAR: "from-env"}, [env_file]) == "from-env"
    assert find_api_key({}, [tmp_path / "missing.env"]) is None
    google = tmp_path / "google.env"
    google.write_text("GOOGLE_API_KEY=from-google-name\n", encoding="utf-8")
    assert find_api_key({}, [google]) == "from-google-name"
    assert find_api_key({"GOOGLE_API_KEY": "env-google"}, [env_file]) == "env-google"


def test_validate_report() -> None:
    good = {"headline": "☠️ HELL WEEK: Oct 19 – Oct 25", "forecast": "Storms.", "advisories": ["A"]}
    assert validate_report(good) == {**good, "source": "gemma"}
    assert validate_report({**good, "advisories": []}) is None
    assert validate_report({**good, "headline": ""}) is None
    assert validate_report(["not", "a", "report"]) is None


# --- CLI end to end -----------------------------------------------------------


@pytest.fixture
def demo_ics(tmp_path: Path) -> Path:
    path = tmp_path / "demo.ics"
    path.write_bytes(build_calendar().to_ical())
    return path


def use_fake_gemma(monkeypatch: pytest.MonkeyPatch, api: FakeApi) -> None:
    def fake_client(required: bool = False) -> GemmaClient:
        return make_client(api)

    monkeypatch.setattr(hellweek.cli, "gemma_client", fake_client)


def smart_answers(prompt: str) -> Any:
    if "weather forecaster" in prompt:
        return [
            {
                "headline": "☠️ HELL WEEK: Oct 15 – Oct 24",
                "forecast": "90% chance of all-nighters.",
                "advisories": ["Start CHEM prep Fri Oct 16.", "Move Sam's birthday dinner."],
            }
        ]
    answers = keyword_answers(prompt)
    for i, title in enumerate(prompt_titles(prompt), 1):
        if title == "CS 220 Project 2 due":
            answers[str(i)] = {"type": "deadline", "prep_hours": 12, "stress": 8}
    return answers


def run_cli(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = hellweek.cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_cli_analyze_with_gemma(
    demo_ics: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = FakeApi(default=smart_answers)
    use_fake_gemma(monkeypatch, api)
    out = tmp_path / "load.json"
    args = ["analyze", str(demo_ics), *RANGE, "--gemma", "--gemma-cache", str(tmp_path / "c.json")]
    code, printed = run_cli([*args, "--out", str(out)], capsys)

    assert code == 0 and KEY not in printed
    (week,) = json.loads(out.read_text(encoding="utf-8"))["hell_weeks"]
    assert week["report"]["source"] == "gemma"
    assert week["report"]["forecast"] == "90% chance of all-nighters."
    project = next(k for k in week["key_events"] if k["title"] == "CS 220 Project 2 due")
    assert project["prep_hours"] == 12
    report_prompt = next(p for p in api.prompts() if "weather forecaster" in p)
    assert "Science Hall" not in report_prompt and "prep_starts" in report_prompt


def test_cli_gemma_outage_falls_back_to_keywords_and_template(
    demo_ics: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_fake_gemma(monkeypatch, FakeApi())  # every call: HTTP 503
    out = tmp_path / "load.json"
    args = ["analyze", str(demo_ics), *RANGE, "--gemma", "--gemma-cache", str(tmp_path / "c.json")]
    code, printed = run_cli([*args, "--out", str(out)], capsys)

    assert code == 0
    assert "keyword" in printed and "template" in printed
    (week,) = json.loads(out.read_text(encoding="utf-8"))["hell_weeks"]
    assert week["report"]["source"] == "template"
    assert week["report"]["headline"].startswith("☠️ HELL WEEK:")


def test_cli_without_gemma_flag_never_calls_the_api(
    demo_ics: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def explode(required: bool = False) -> GemmaClient:
        raise AssertionError("Gemma must be opt-in")

    monkeypatch.setattr(hellweek.cli, "gemma_client", explode)
    out = tmp_path / "load.json"
    code, _ = run_cli(["analyze", str(demo_ics), *RANGE, "--out", str(out)], capsys)
    assert code == 0
    (week,) = json.loads(out.read_text(encoding="utf-8"))["hell_weeks"]
    assert week["report"]["source"] == "template"


def test_cli_gemma_flag_without_key_warns_and_falls_back(
    demo_ics: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(hellweek.cli, "find_api_key", lambda: None)
    out = tmp_path / "load.json"
    code, printed = run_cli(
        ["analyze", str(demo_ics), *RANGE, "--gemma", "--out", str(out)], capsys
    )
    assert code == 0 and API_KEY_VAR in printed


def test_cli_classify_writes_classes_json(
    demo_ics: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    use_fake_gemma(monkeypatch, FakeApi(default=smart_answers))
    out = tmp_path / "classes.json"
    args = ["classify", str(demo_ics), *RANGE, "--gemma-cache", str(tmp_path / "c.json")]
    code, _ = run_cli([*args, "--out", str(out)], capsys)
    assert code == 0
    classes = json.loads(out.read_text(encoding="utf-8"))
    assert all(set(v) == {"type", "prep_hours", "stress"} for v in classes.values())
    assert any(v == {"type": "deadline", "prep_hours": 12.0, "stress": 8} for v in classes.values())


def test_template_report_uses_only_given_facts() -> None:
    facts = {
        "hell_week": {
            "start": "Mon Oct 19",
            "end": "Sun Oct 25",
            "busiest_7_days": "Mon Oct 19 to Sun Oct 25",
            "hours_in_busiest_7_days": 60.0,
            "normal_week_hours": 20.0,
        },
        "high_stakes_events": [
            {
                "title": "Midterm",
                "type": "exam",
                "date": "Wed Oct 21",
                "prep_hours": 10.0,
                "prep_starts": "Sat Oct 17",
            }
        ],
    }
    report = template_report(facts)
    assert report["headline"] == "☠️ HELL WEEK: Mon Oct 19 – Sun Oct 25"
    assert "3.0x" in report["forecast"]
    assert report["advisories"] == ["Start Midterm prep by Sat Oct 17 (10h)."]
