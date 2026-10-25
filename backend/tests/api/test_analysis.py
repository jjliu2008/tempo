"""POST /api/v1/analysis end to end, with Gemma faked and the network local."""

import http.server
import json
import threading
from collections.abc import AsyncIterator, Iterator, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

import app.services.analysis as calendar_service
from app.core.config import Settings
from app.main import create_app
from hellweek.gemma import GemmaClient
from hellweek.make_demo import build_calendar

SECRET = "private-0123456789abcdefSECRET"
FIXTURE = Path(__file__).parents[1] / "hellweek" / "fixtures" / "edge_cases.ics"


@pytest.fixture(autouse=True)
def no_key_no_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Never touch a real key or the shared cache from tests."""
    monkeypatch.setattr(
        "app.api.v1.endpoints.analysis.settings", Settings(_env_file=None, GOOGLE_API_KEY=None)
    )
    monkeypatch.setattr(calendar_service, "GEMMA_CACHE", tmp_path / "cache.json")


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture(scope="module")
def ics_server() -> Iterator[str]:
    body = build_calendar().to_ical()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            ok = self.path.endswith("/basic.ics") and SECRET in self.path
            self.send_response(200 if ok else 404)
            self.end_headers()
            self.wfile.write(body if ok else b"nope")

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


async def analyze(client: httpx.AsyncClient, **body: Any) -> httpx.Response:
    return await client.post("/api/v1/analysis", json=body)


async def test_demo_semester_finds_week_9(client: httpx.AsyncClient) -> None:
    response = await analyze(client, source="demo", gemma=False)
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["classifier"] == "keywords"
    assert len(data["days"]) == 113
    (week,) = data["hell_weeks"]
    assert week["start"] <= "2026-10-25" and week["end"] >= "2026-10-19"
    assert week["report"]["source"] == "template"
    assert data["events"] and data["prep_blocks"]


DEMO_HELL_WEEKS = {
    "engineering": ("2026-10-15", "2026-10-23"),
    "social-crunch": ("2026-10-15", "2026-10-26"),
    "work-crunch": ("2026-10-22", "2026-11-02"),
    "humanities": ("2026-11-05", "2026-11-15"),
}


@pytest.mark.parametrize("variant", sorted(DEMO_HELL_WEEKS))
async def test_each_demo_semester_has_its_own_hell_week(
    client: httpx.AsyncClient, variant: str
) -> None:
    response = await analyze(client, source="demo", demo=variant, gemma=False)
    assert response.status_code == 200
    (week,) = response.json()["hell_weeks"]
    assert (week["start"], week["end"]) == DEMO_HELL_WEEKS[variant]


async def test_social_demo_is_busier_and_more_social_than_the_default(
    client: httpx.AsyncClient,
) -> None:
    async def titles(variant: str) -> list[str]:
        data = (await analyze(client, source="demo", demo=variant, gemma=False)).json()
        return [e["title"] for e in data["events"]]

    default, social = await titles("engineering"), await titles("social-crunch")
    assert len(social) > len(default)
    assert {"Greek formal", "Football tailgate", "Karaoke night"} <= set(social) - set(default)


async def test_unknown_demo_semester_is_rejected(client: httpx.AsyncClient) -> None:
    response = await analyze(client, source="demo", demo="astronomy")
    assert response.status_code == 422


async def test_uploaded_ics(client: httpx.AsyncClient) -> None:
    response = await analyze(
        client,
        source="ics",
        ics=FIXTURE.read_text(encoding="utf-8"),
        start="2026-10-01",
        end="2026-11-30",
        gemma=False,
    )
    assert response.status_code == 200
    titles = {e["title"] for e in response.json()["events"]}
    assert "CHEM 101 Lecture" in titles and "Halloween party" not in titles


async def test_calendar_url_is_fetched(client: httpx.AsyncClient, ics_server: str) -> None:
    url = f"{ics_server}/calendar/ical/x/{SECRET}/basic.ics"
    response = await analyze(
        client, source="url", url=url, start="2026-10-19", end="2026-10-25", gemma=False
    )
    assert response.status_code == 200
    assert SECRET not in response.text


@pytest.mark.parametrize(
    "url",
    [
        "{server}/calendar/ical/x/wrong-path/basic.ics",
        "calendar.google.com/calendar/ical/x/{secret}/basic.ics",
        "https://calendar.google.com:bad/calendar/ical/x/{secret}/basic.ics",
    ],
)
async def test_bad_url_errors_never_echo_it(
    client: httpx.AsyncClient, ics_server: str, url: str
) -> None:
    body = {"source": "url", "url": url.format(server=ics_server, secret=SECRET)}
    response = await analyze(client, **body, start="2026-10-19", end="2026-10-25")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "calendar_invalid"
    assert "SECRET" not in response.text and "wrong-path" not in response.text


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"source": "ics", "ics": "", "start": "2026-10-01", "end": "2026-10-02"}, "Upload"),
        ({"source": "ics", "ics": "BEGIN:VCALENDAR\nEND:VCALENDAR"}, "start and end"),
        ({"source": "demo", "start": "2026-12-01", "end": "2026-09-01"}, "on or before"),
        ({"source": "demo", "start": "2026-01-01", "end": "2027-12-31"}, "at most"),
        ({"source": "demo", "tz": "Mars/Olympus"}, "Unknown timezone"),
        ({"source": "ics", "ics": "<html>", "start": "2026-10-01", "end": "2026-10-02"}, "not an"),
    ],
)
async def test_bad_requests_get_readable_errors(
    client: httpx.AsyncClient, body: dict[str, Any], message: str
) -> None:
    response = await analyze(client, gemma=False, **body)
    assert response.status_code == 400
    assert message in response.json()["detail"]["message"]


async def test_gemma_without_key_falls_back(client: httpx.AsyncClient) -> None:
    response = await analyze(client, source="demo", gemma=True)
    assert response.status_code == 200
    assert response.json()["meta"]["classifier"] == "keywords"


async def test_gemma_classifies_and_writes_the_forecast(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def transport(url: str, body: bytes, headers: Mapping[str, str], timeout: float) -> bytes:
        prompt = json.loads(body)["contents"][0]["parts"][0]["text"]
        if "weather forecaster" in prompt:
            answer: Any = {
                "headline": "☠️ HELL WEEK: Oct 15 – Oct 24",
                "forecast": "Midterm front moving in.",
                "advisories": ["Start CHEM prep Fri Oct 16."],
            }
        else:
            lines = [ln for ln in prompt.splitlines() if ln[:1].isdigit() and '. "' in ln]
            answer = {}
            for line in lines:
                number, title = line.split(". ", 1)
                exam = "Midterm" in title
                answer[number] = {
                    "type": "exam" if exam else "deadline" if "due" in title else "class",
                    "prep_hours": 10 if exam else 6 if "due" in title else 0,
                    "stress": 9 if exam else 7 if "due" in title else 2,
                }
        parts = [{"text": json.dumps(answer)}]
        return json.dumps({"candidates": [{"content": {"parts": parts}}]}).encode()

    monkeypatch.setattr(
        calendar_service,
        "gemma_client",
        lambda settings: GemmaClient("fake", models=("m",), transport=transport),
    )
    response = await analyze(client, source="demo", gemma=True)
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["classifier"] == "gemma"
    assert data["hell_weeks"][0]["report"] == {
        "headline": "☠️ HELL WEEK: Oct 15 – Oct 24",
        "forecast": "Midterm front moving in.",
        "advisories": ["Start CHEM prep Fri Oct 16."],
        "source": "gemma",
    }


def parsed_event(
    id: str, title: str, start: str, end: str, all_day: bool = False
) -> dict[str, Any]:
    """The shape POST /calendars/{provider}/parse returns, extra fields included."""
    return {
        "provider": "google",
        "calendar_id": "primary",
        "calendar_name": "School",
        "id": id,
        "title": title,
        "start": start,
        "end": end,
        "all_day": all_day,
        "duration_hours": 0,
        "location": "Science Hall 101",
        "description": "secret notes",
    }


async def test_events_from_the_calendar_parser(client: httpx.AsyncClient) -> None:
    events = [
        parsed_event(
            "m1", "CHEM Midterm", "2026-10-20T19:00:00-04:00", "2026-10-20T21:00:00-04:00"
        ),
        parsed_event(
            "m2", "MATH Midterm", "2026-10-21T16:00:00-04:00", "2026-10-21T18:00:00-04:00"
        ),
        parsed_event(
            "p", "Project due", "2026-10-22T00:00:00-04:00", "2026-10-23T00:00:00-04:00", True
        ),
        parsed_event("old", "Old exam", "2026-01-05T09:00:00-05:00", "2026-01-05T10:00:00-05:00"),
    ] + [
        parsed_event(
            f"w{d}",
            "Work shift",
            f"2026-10-{d:02d}T09:00:00-04:00",
            f"2026-10-{d:02d}T17:00:00-04:00",
        )
        for d in range(12, 25)
    ]
    response = await analyze(
        client,
        source="events",
        events=events,
        start="2026-10-01",
        end="2026-10-31",
        tz="America/New_York",
        gemma=False,
    )
    assert response.status_code == 200
    data = response.json()
    ids = {e["id"] for e in data["events"]}
    assert {"m1", "m2", "p"} <= ids and "old" not in ids
    project = next(e for e in data["events"] if e["id"] == "p")
    assert project["all_day"] and project["start"].startswith("2026-10-22T00:00:00")
    shift = next(e for e in data["events"] if e["id"] == "w12")
    assert shift["start"] == "2026-10-12T09:00:00-04:00"
    assert "Science Hall" not in response.text and "secret notes" not in response.text
    (week,) = data["hell_weeks"]
    assert {k["event_id"] for k in week["key_events"]} == {"m1", "m2", "p"}


async def test_events_source_needs_events(client: httpx.AsyncClient) -> None:
    response = await analyze(
        client, source="events", events=[], start="2026-10-01", end="2026-10-31", gemma=False
    )
    assert response.status_code == 400
    assert "no events" in response.json()["detail"]["message"]
