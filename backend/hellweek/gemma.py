"""Gemma via the Gemini API, for the two jobs that need judgment or writing:

1. Estimate the hidden prep behind each event title (type, prep_hours, stress).
2. Write the hell week forecast from facts our code computed.

Parsing, prep spreading, load math and detection never touch the model. Gemma
only ever sees event titles plus dates and hours we computed; no locations,
descriptions or calendar URLs. The API key comes from GEMINI_API_KEY or
GOOGLE_API_KEY (environment, then backend/.env), travels in a header (never
a URL), and is never printed.
"""

from __future__ import annotations

import http.client
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hellweek.classify import Classification, parse_entry
from hellweek.parse import Event
from hellweek.report import validate_report

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
API_KEY_VAR = "GEMINI_API_KEY"
# Same names the FastAPI settings accept (app/core/config.py), so one .env serves both.
API_KEY_VARS = (API_KEY_VAR, "GOOGLE_API_KEY")
MODEL_VAR = "HELLWEEK_GEMMA_MODEL"
# The MoE model answers faster; the dense one is the fallback when it is busy.
DEFAULT_MODELS = ("gemma-4-26b-a4b-it", "gemma-4-31b-it")
BACKEND_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
BATCH_SIZE = 40
MAX_WORKERS = 3
MAX_PREP_HOURS = 40.0
CACHE_VERSION = "v1"

Transport = Callable[[str, bytes, Mapping[str, str], float], bytes]


class GemmaError(Exception):
    """Gemma could not help. Messages never include the API key."""


class ApiError(GemmaError):
    def __init__(self, status: int | None, detail: str, retry_after: float | None = None):
        super().__init__(f"HTTP {status}: {detail}" if status else detail)
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.status is None or self.status in RETRYABLE_STATUS


# --- configuration -----------------------------------------------------------


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip("'\"")
    return values


def find_api_key(
    environ: Mapping[str, str] = os.environ,
    env_files: Sequence[Path] = (Path(".env"), BACKEND_ENV_FILE),
) -> str | None:
    sources = [environ, *(read_env_file(path) for path in env_files)]
    for source in sources:
        for name in API_KEY_VARS:
            if source.get(name, "").strip():
                return source[name].strip()
    return None


def configured_models(environ: Mapping[str, str] = os.environ) -> tuple[str, ...]:
    chosen = environ.get(MODEL_VAR, "").strip()
    return (chosen,) if chosen else DEFAULT_MODELS


# --- transport and client ----------------------------------------------------


def retry_delay(retry_after: str | None, body: bytes) -> float | None:
    """Seconds the server asked us to wait: Retry-After, or Google's RetryInfo."""
    if retry_after and retry_after.strip().isdigit():
        return float(retry_after)
    match = re.search(rb'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body)
    return float(match.group(1)) if match else None


def api_message(body: bytes) -> str:
    try:
        return str(json.loads(body)["error"]["message"])[:200]
    except (ValueError, KeyError, TypeError):
        return "request failed"


def urllib_transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data: bytes = resp.read()
            return data
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        raise ApiError(
            exc.code, api_message(raw), retry_delay(exc.headers.get("Retry-After"), raw)
        ) from None
    except (OSError, http.client.HTTPException) as exc:
        raise ApiError(None, f"network error ({type(exc).__name__})") from None


def response_text(payload: Mapping[str, Any]) -> str:
    """The answer text, skipping the model's thought parts."""
    try:
        candidate = payload["candidates"][0]
        parts = candidate.get("content", {}).get("parts", [])
    except (KeyError, IndexError, TypeError):
        raise GemmaError("response had no candidates") from None
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise GemmaError(f"empty response (finishReason={candidate.get('finishReason')})")
    return text


def parse_json_text(text: str) -> Any:
    """JSON from model text, tolerating ```json fences or chatter around it."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except ValueError:
                pass
    raise GemmaError("response was not valid JSON")


def unwrap(raw: Any) -> Any:
    """Gemma sometimes wraps the requested object in a one-item list."""
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], Mapping):
        return raw[0]
    return raw


def backoff_seconds(attempt: int, requested: float | None) -> float:
    base = requested if requested is not None else 2.0 * 2**attempt
    return min(base, 60.0) + random.uniform(0, 1)


@dataclass
class GemmaClient:
    api_key: str
    models: Sequence[str] = DEFAULT_MODELS
    transport: Transport = urllib_transport
    timeout: float = 120.0
    max_attempts: int = 4
    sleep: Callable[[float], None] = time.sleep
    calls: int = field(default=0, init=False)

    def generate_json(self, prompt: str, temperature: float = 0.0) -> Any:
        """Ask each model in turn, retrying rate limits, overloads and bad JSON."""
        last: GemmaError = GemmaError("no models configured")
        for model in self.models:
            for attempt in range(self.max_attempts):
                try:
                    return parse_json_text(response_text(self._post(model, prompt, temperature)))
                except ApiError as exc:
                    last = exc
                    if exc.status in (401, 403):
                        raise GemmaError(f"API key rejected ({exc})") from None
                    if not exc.retryable:
                        break  # e.g. 404 model not found, 400 bad request: try the next model
                    if attempt + 1 < self.max_attempts:
                        self.sleep(backoff_seconds(attempt, exc.retry_after))
                except GemmaError as exc:
                    last = exc
        raise GemmaError(f"Gemma unavailable: {last}")

    def _post(self, model: str, prompt: str, temperature: float) -> Mapping[str, Any]:
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingLevel": "minimal"},
            },
        }
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        self.calls += 1
        raw = self.transport(
            API_URL.format(model=model), json.dumps(body).encode(), headers, self.timeout
        )
        try:
            payload: Mapping[str, Any] = json.loads(raw)
        except ValueError:
            raise GemmaError("API returned non-JSON") from None
        return payload


# --- job 1: hidden prep behind each title -------------------------------------

CLASSIFY_PROMPT = """You estimate the hidden workload behind a college student's calendar events.
For each numbered event title, return:
- "type": one of exam, deadline, quiz, class, meeting, social, work, other
- "prep_hours": hours of work the student must do BEFORE the event (studying, writing,
  building). Not the event's own length. Lectures, labs, meetings, social events, shifts,
  review sessions and office hours are usually 0.
- "stress": integer 1-10, how heavily the event weighs on the student.
Rough guide: midterm 8-12h prep, stress 8-9. Final exam 12-20h, stress 9-10.
Quiz 1-3h, stress 3-5. Homework due 2-5h, stress 5-6. Essay or project due 5-15h, stress 6-8.
Examples:
"CSE 232 Midterm 2" -> {{"type": "exam", "prep_hours": 10, "stress": 9}}
"Lunch w/ Sam" -> {{"type": "social", "prep_hours": 0, "stress": 1}}
"STT 351 HW 6 due" -> {{"type": "deadline", "prep_hours": 4, "stress": 6}}
"Club meeting" -> {{"type": "meeting", "prep_hours": 0, "stress": 2}}
Return ONLY a JSON object keyed by event number, e.g. {{"1": {{...}}, "2": {{...}}}}.
Events:
{events}"""


def unique_titles(titles: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(t.strip() for t in titles if t.strip()))


def classify_prompt(titles: Sequence[str]) -> str:
    lines = "\n".join(f"{i}. {json.dumps(t, ensure_ascii=False)}" for i, t in enumerate(titles, 1))
    return CLASSIFY_PROMPT.format(events=lines)


def parse_batch(raw: Any, titles: Sequence[str]) -> dict[str, Classification]:
    """Validated entries by title. Numbering avoids depending on Gemma copying
    titles back exactly; missing or malformed entries are simply left out."""
    if isinstance(raw, list) and len(raw) == len(titles) and all("type" in r for r in raw):
        raw = {str(i): entry for i, entry in enumerate(raw, 1)}  # a plain list of entries
    raw = unwrap(raw)
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, Classification] = {}
    for i, title in enumerate(titles, 1):
        entry = parse_entry(raw.get(str(i)))
        if entry is not None:
            prep = min(entry.prep_hours, MAX_PREP_HOURS)
            result[title] = Classification(entry.type, prep, max(1, entry.stress))
    return result


def classify_titles(
    titles: Sequence[str], client: GemmaClient, batch_size: int = BATCH_SIZE
) -> tuple[dict[str, Classification], list[str]]:
    """Classify unique titles in parallel batches. Returns (results, batch errors)."""
    todo = unique_titles(titles)
    batches = [todo[i : i + batch_size] for i in range(0, len(todo), batch_size)]

    def run(batch: list[str]) -> tuple[dict[str, Classification], str | None]:
        try:
            return parse_batch(client.generate_json(classify_prompt(batch)), batch), None
        except GemmaError as exc:
            return {}, str(exc)

    results: dict[str, Classification] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for found, error in pool.map(run, batches):
            results.update(found)
            if error:
                errors.append(error)
    return results, errors


def load_cache(path: Path | None) -> dict[str, Classification]:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8")).get(CACHE_VERSION, {})
    except (OSError, ValueError, AttributeError):
        return {}
    return {t: c for t, raw in data.items() if (c := parse_entry(raw)) is not None}


def save_cache(path: Path | None, entries: Mapping[str, Classification]) -> None:
    if path is None:
        return
    data = {
        CACHE_VERSION: {
            t: {"type": c.type, "prep_hours": c.prep_hours, "stress": c.stress}
            for t, c in sorted(entries.items())
        }
    }
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class ClassifyResult:
    by_event_id: dict[str, Classification]
    from_gemma: int
    from_cache: int
    missing_titles: list[str]
    errors: list[str]


def gemma_classify_events(
    events: Sequence[Event], client: GemmaClient, cache_path: Path | None = None
) -> ClassifyResult:
    """Gemma classifications keyed by event id, for every event whose title it
    covered. Callers fall back to keywords for the rest (see classify_events)."""
    titles = unique_titles([e.title for e in events])
    cached = load_cache(cache_path)
    todo = [t for t in titles if t not in cached]
    fresh, errors = classify_titles(todo, client) if todo else ({}, [])
    if fresh:
        save_cache(cache_path, {**cached, **fresh})
    by_title = {**cached, **fresh}
    return ClassifyResult(
        by_event_id={
            e.id: by_title[e.title.strip()] for e in events if e.title.strip() in by_title
        },
        from_gemma=len(fresh),
        from_cache=sum(t in cached for t in titles),
        missing_titles=[t for t in titles if t not in by_title],
        errors=errors,
    )


# --- job 2: the weather report -------------------------------------------------

REPORT_PROMPT = """You are a campus weather forecaster warning a college student about a
"hell week" their calendar is heading into. Write a short, funny forecast in weather-report
style, then real, specific advice.
Rules:
- Use ONLY the dates, events and hours in the facts below. Do not invent events or numbers.
- Advice must name real events and dates from the facts: when to start prep (use
  prep_starts), and which other_events could be moved or skipped.
- Keep it kind and practical; no medical or diet advice.
Example of the style:
{{"headline": "☠️ HELL WEEK: Oct 26 – Nov 1",
 "forecast": "90% chance of all-nighters. Heavy midterm activity moving in Wednesday.",
 "advisories": ["Start the STT homework by Oct 22.", "Move Thursday's lunch."]}}
Return ONLY JSON with exactly these keys: "headline" (starts with "☠️ HELL WEEK:" and the
dates), "forecast" (1-2 sentences), "advisories" (2-4 short tips).
Facts:
{facts}"""


def gemma_report(facts: Mapping[str, Any], client: GemmaClient) -> dict[str, Any] | None:
    """Gemma's forecast for one hell week, or None if it failed or was malformed."""
    prompt = REPORT_PROMPT.format(facts=json.dumps(facts, indent=1, ensure_ascii=False))
    try:
        report = validate_report(unwrap(client.generate_json(prompt, temperature=0.9)))
    except GemmaError as exc:
        print(f"warning: Gemma forecast failed, using template ({exc})", file=sys.stderr)
        return None
    if report is None:
        print("warning: Gemma forecast had the wrong shape, using template", file=sys.stderr)
    return report
