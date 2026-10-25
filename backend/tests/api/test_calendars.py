"""Calendar API integration tests.

The FastAPI app, CalendarService, CalendarRepository and the SQLite database are real.
Only vendor HTTP (Google, Apple CalDAV) and the public ICS feed fetch are mocked.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit
from zoneinfo import ZoneInfo

import httpx
import icalendar
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.api.deps import get_calendar_service
from app.core.config import Settings
from app.main import create_app
from app.repositories.calendar import CalendarRepository
from app.services.calendar import CalendarService
from app.services.calendar_errors import CalendarError
from app.services.google_calendar import (
    AUTHORIZATION_ENDPOINT,
    CALENDAR_API,
    CALENDAR_READ_SCOPE,
    TOKEN_ENDPOINT,
    USERINFO_ENDPOINT,
)

pytestmark = pytest.mark.asyncio

API = "/api/v1/calendars"
FRONTEND = "http://localhost:5173"
ORIGIN = FRONTEND
GOOGLE_REDIRECT = f"{FRONTEND}/api/v1/calendars/google/callback"
GOOGLE_CLIENT_SECRET = "google-client-secret-value"
GOOGLE_CODE = "auth-code-1"
GOOGLE_ACCESS = "ya29.access-token-value"
GOOGLE_REFRESH = "1//refresh-token-value"
GOOGLE_EMAIL = "owner@example.com"
APPLE_EMAIL = "owner@icloud.com"
APPLE_PASSWORD = "abcd-efgh-ijkl-mnop"
WRONG_APPLE_PASSWORD = "wxyz-wxyz-wxyz-wxyz"
NEW_YORK = ZoneInfo("America/New_York")

PRINCIPAL_PATH = "/123456789/principal/"
HOME_PATH = "/123456789/calendars/"
WORK_PATH = "/123456789/calendars/work-uuid/"
FALLBACK_PATH = "/123456789/calendars/fallback-uuid/"

WINDOW = {"start": "2025-01-06", "end": "2025-01-20", "timezone": "America/New_York"}
APPLE_BODY = {"email": APPLE_EMAIL, "app_password": APPLE_PASSWORD}
PARSE_BODY = {**WINDOW, "calendar_ids": ["work@example.com"]}
IMPORT_BODY = {**WINDOW, "url": "https://feeds.example.com/team.ics"}


# --- Harness -----------------------------------------------------------------------------


class Upstream:
    """Routes every vendor request. Unmatched requests fail closed with HTTP 500."""

    def __init__(self) -> None:
        self.handler: Callable[[httpx.Request], httpx.Response] = lambda _request: httpx.Response(
            500
        )
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


@dataclass
class Harness:
    app: FastAPI
    client: httpx.AsyncClient
    http: httpx.AsyncClient
    service: CalendarService
    engine: AsyncEngine
    key: str
    upstream: Upstream
    cookie_name: str

    async def close(self) -> None:
        await self.client.aclose()
        await self.http.aclose()
        await self.engine.dispose()


async def build_harness(directory: Path, environment: str = "development") -> Harness:
    key = Fernet.generate_key().decode()
    settings = Settings(
        _env_file=None,
        ENVIRONMENT=environment,
        CALENDAR_FRONTEND_URL=FRONTEND,
        CALENDAR_ENCRYPTION_KEY=SecretStr(key),
        GOOGLE_CALENDAR_CLIENT_ID="google-client-id",
        GOOGLE_CALENDAR_CLIENT_SECRET=SecretStr(GOOGLE_CLIENT_SECRET),
        GOOGLE_CALENDAR_REDIRECT_URI=GOOGLE_REDIRECT,
    )
    engine = create_async_engine(f"sqlite+aiosqlite:///{directory / 'calendar.db'}")
    upstream = Upstream()
    http = httpx.AsyncClient(transport=httpx.MockTransport(upstream), follow_redirects=False)
    repository = CalendarRepository(engine, async_sessionmaker(engine, expire_on_commit=False))
    service = CalendarService(settings, repository, http)
    app = create_app()
    app.dependency_overrides[get_calendar_service] = lambda: service
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return Harness(
        app=app,
        client=client,
        http=http,
        service=service,
        engine=engine,
        key=key,
        upstream=upstream,
        cookie_name=service.cookie_name,
    )


@pytest_asyncio.fixture
async def harness(tmp_path: Path) -> AsyncIterator[Harness]:
    built = await build_harness(tmp_path)
    try:
        yield built
    finally:
        await built.close()


@pytest.fixture(autouse=True)
def no_feed_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """URL import tests must opt in to a fetch; any unexpected fetch fails loudly."""

    async def refuse(url: str) -> icalendar.Calendar:
        raise AssertionError("unexpected calendar feed fetch")

    monkeypatch.setattr("app.services.calendar.fetch_calendar_feed", refuse)


@dataclass(frozen=True)
class Browser:
    cookie: str
    csrf: str


async def open_browser(h: Harness) -> Browser:
    response = await h.client.get(f"{API}/session")
    assert response.status_code == 200
    browser = Browser(cookie=response.cookies[h.cookie_name], csrf=response.json()["csrf_token"])
    # Keep the client jar empty so every request states its browser explicitly.
    h.client.cookies.clear()
    return browser


def cookies(h: Harness, b: Browser) -> dict[str, str]:
    return {h.cookie_name: b.cookie}


def guarded(b: Browser) -> dict[str, str]:
    return {"X-CSRF-Token": b.csrf, "Origin": ORIGIN}


async def post_as(
    h: Harness, b: Browser, path: str, body: dict[str, Any] | None = None
) -> httpx.Response:
    return await h.client.post(f"{API}{path}", json=body, headers=guarded(b), cookies=cookies(h, b))


async def delete_as(h: Harness, b: Browser, path: str) -> httpx.Response:
    return await h.client.delete(f"{API}{path}", headers=guarded(b), cookies=cookies(h, b))


async def get_as(h: Harness, b: Browser, path: str) -> httpx.Response:
    return await h.client.get(f"{API}{path}", cookies=cookies(h, b))


async def sql(h: Harness, statement: str, **params: Any) -> list[tuple[Any, ...]]:
    async with h.engine.begin() as conn:
        result = await conn.execute(text(statement), params)
        return [tuple(row) for row in result.fetchall()] if result.returns_rows else []


async def connection_count(h: Harness) -> int:
    return (await sql(h, "SELECT COUNT(*) FROM calendar_connections"))[0][0]


def detail(response: httpx.Response) -> dict[str, Any]:
    return response.json()["detail"]


# --- Google fake ---------------------------------------------------------------------------

WORK_CALENDAR = {
    "id": "work@example.com",
    "summary": "Work",
    "accessRole": "owner",
    "timeZone": "America/New_York",
    "primary": True,
}
CALENDAR_PAGES = [
    [
        WORK_CALENDAR,
        {
            "id": "holidays@group.v.calendar.google.com",
            "summary": "Holidays",
            "accessRole": "reader",
        },
    ],
    [
        {"id": "shared@example.com", "summary": "Shared", "accessRole": "writer"},
        {"id": "busy@example.com", "summary": "Busy", "accessRole": "freeBusyReader"},
    ],
]
TIMED_EVENT = {
    "id": "evt-timed",
    "status": "confirmed",
    "summary": "Lab",
    "location": "Room 1",
    "description": "Bring kit",
    "start": {"dateTime": "2025-01-06T14:00:00-05:00"},
    "end": {"dateTime": "2025-01-06T15:30:00-05:00"},
}
CANCELLED_EVENT = {
    "id": "evt-cancelled",
    "status": "cancelled",
    "summary": "Dropped",
    "start": {"dateTime": "2025-01-07T14:00:00-05:00"},
    "end": {"dateTime": "2025-01-07T15:00:00-05:00"},
}
ALL_DAY_EVENT = {
    "id": "evt-allday",
    "status": "confirmed",
    "summary": "Holiday",
    "start": {"date": "2025-01-20"},
    "end": {"date": "2025-01-21"},
}
EVENT_PAGES: dict[str, list[list[dict[str, Any]]]] = {
    "work@example.com": [[TIMED_EVENT, CANCELLED_EVENT], [ALL_DAY_EVENT]],
}


def _page(pages: list[list[dict[str, Any]]], request: httpx.Request) -> httpx.Response:
    token = request.url.params.get("pageToken")
    index = int(token.removeprefix("page-")) if token else 0
    body: dict[str, Any] = {"items": pages[index]}
    if index + 1 < len(pages):
        body["nextPageToken"] = f"page-{index + 1}"
    return httpx.Response(200, json=body)


def google_upstream(
    calendars: list[list[dict[str, Any]]], events: dict[str, list[list[dict[str, Any]]]]
) -> Callable[[httpx.Request], httpx.Response]:
    def handle(request: httpx.Request) -> httpx.Response:
        base = str(request.url.copy_with(query=None))
        if request.method == "POST" and base == TOKEN_ENDPOINT:
            if parse_qs(request.content.decode()).get("code") == [GOOGLE_CODE]:
                return httpx.Response(
                    200,
                    json={
                        "access_token": GOOGLE_ACCESS,
                        "expires_in": 3600,
                        "refresh_token": GOOGLE_REFRESH,
                        "scope": f"openid email {CALENDAR_READ_SCOPE}",
                    },
                )
            return httpx.Response(400, json={"error": "invalid_grant"})
        if base == USERINFO_ENDPOINT:
            return httpx.Response(200, json={"email": GOOGLE_EMAIL})
        if base == f"{CALENDAR_API}/users/me/calendarList":
            return _page(calendars, request)
        prefix = f"{CALENDAR_API}/calendars/"
        if base.startswith(prefix) and base.endswith("/events"):
            calendar_id = unquote(base[len(prefix) : -len("/events")])
            return _page(events.get(calendar_id, [[]]), request)
        return httpx.Response(404)

    return handle


def use_google(h: Harness) -> None:
    h.upstream.handler = google_upstream(CALENDAR_PAGES, EVENT_PAGES)


async def google_state(h: Harness, b: Browser) -> str:
    response = await post_as(h, b, "/google/authorize")
    assert response.status_code == 200
    return parse_qs(urlsplit(response.json()["authorization_url"]).query)["state"][0]


async def connect_google(h: Harness, b: Browser) -> None:
    state = await google_state(h, b)
    response = await h.client.get(
        f"{API}/google/callback",
        params={"state": state, "code": GOOGLE_CODE},
        cookies=cookies(h, b),
    )
    assert response.status_code == 303


# --- Apple fake ----------------------------------------------------------------------------


def _xml(body: str, status: int = 207) -> httpx.Response:
    return httpx.Response(
        status,
        content=(
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
            f"{body}</D:multistatus>"
        ).encode(),
    )


PRINCIPAL_BODY = (
    "<D:response><D:href>/</D:href><D:propstat><D:prop>"
    f"<D:current-user-principal><D:href>{PRINCIPAL_PATH}</D:href></D:current-user-principal>"
    "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
)
HOME_SET_BODY = (
    f"<D:response><D:href>{PRINCIPAL_PATH}</D:href><D:propstat><D:prop>"
    f"<C:calendar-home-set><D:href>{HOME_PATH}</D:href></C:calendar-home-set>"
    "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
)
VTIMEZONE = (
    "BEGIN:VTIMEZONE\nTZID:America/New_York\n"
    "BEGIN:STANDARD\nDTSTART:19701101T020000\nTZOFFSETFROM:-0400\nTZOFFSETTO:-0500\n"
    "END:STANDARD\nEND:VTIMEZONE"
)


def _listing_entry(
    href: str,
    *,
    resource: str = "<D:collection/><C:calendar/>",
    components: str | None = '<C:comp name="VEVENT"/>',
    name: str | None = None,
    timezone: str | None = None,
) -> str:
    props = f"<D:resourcetype>{resource}</D:resourcetype>"
    if name is not None:
        props += f"<D:displayname>{name}</D:displayname>"
    if components is not None:
        props += (
            f"<C:supported-calendar-component-set>{components}</C:supported-calendar-component-set>"
        )
    if timezone is not None:
        props += f"<C:calendar-timezone>{timezone}</C:calendar-timezone>"
    return (
        f"<D:response><D:href>{href}</D:href><D:propstat><D:prop>{props}</D:prop>"
        "<D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
    )


LISTING_BODY = "".join(
    [
        _listing_entry(HOME_PATH, resource="<D:collection/>", components=None),
        _listing_entry(WORK_PATH, name="Work", timezone=f"<![CDATA[{VTIMEZONE}]]>"),
        _listing_entry(FALLBACK_PATH),
        _listing_entry("/123456789/calendars/tasks-uuid/", components='<C:comp name="VTODO"/>'),
        _listing_entry("/123456789/calendars/inbox/", resource="<D:collection/>", components=None),
        _listing_entry(f"{WORK_PATH}nested/", name="Nested"),
    ]
)

EVENT_SERIES = "\n".join(
    [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Apple Inc.//iCal//EN",
        VTIMEZONE,
        "BEGIN:VEVENT",
        "UID:standup-1",
        "DTSTAMP:20250101T000000Z",
        "DTSTART;TZID=America/New_York:20250106T090000",
        "DTEND;TZID=America/New_York:20250106T091500",
        "RRULE:FREQ=WEEKLY;COUNT=10",
        "SUMMARY:Standup",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
)
EVENT_OVERRIDE = "\n".join(
    [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        VTIMEZONE,
        "BEGIN:VEVENT",
        "UID:standup-1",
        "DTSTAMP:20250101T000000Z",
        "RECURRENCE-ID;TZID=America/New_York:20250113T090000",
        "DTSTART;TZID=America/New_York:20250113T100000",
        "DTEND;TZID=America/New_York:20250113T101500",
        "SUMMARY:Standup moved",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
)


def _report_entry(href: str, data: str) -> str:
    return (
        f"<D:response><D:href>{href}</D:href><D:propstat><D:prop>"
        f"<C:calendar-data>{data}</C:calendar-data>"
        "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
    )


REPORT_BODY = _report_entry(f"{WORK_PATH}standup-1.ics", EVENT_SERIES) + _report_entry(
    f"{WORK_PATH}standup-1-override.ics", EVENT_OVERRIDE
)


def apple_upstream(request: httpx.Request) -> httpx.Response:
    expected = "Basic " + base64.b64encode(f"{APPLE_EMAIL}:{APPLE_PASSWORD}".encode()).decode()
    if request.headers.get("Authorization") != expected:
        return httpx.Response(401)
    path = request.url.path
    if request.method == "PROPFIND":
        bodies = {"/": PRINCIPAL_BODY, PRINCIPAL_PATH: HOME_SET_BODY, HOME_PATH: LISTING_BODY}
        if path in bodies:
            return _xml(bodies[path])
    if request.method == "REPORT" and path == WORK_PATH:
        return _xml(REPORT_BODY)
    return httpx.Response(404)


def use_apple(h: Harness) -> None:
    h.upstream.handler = apple_upstream


# --- Session and CSRF ----------------------------------------------------------------------


async def test_session_cookie_is_http_only_and_path_scoped(harness: Harness) -> None:
    response = await harness.client.get(f"{API}/session")
    assert response.status_code == 200
    cookie = next(
        v for v in response.headers.get_list("set-cookie") if v.startswith("calendar_session=")
    )
    attributes = {part.strip().lower() for part in cookie.split(";")}
    assert "httponly" in attributes
    assert "path=/" in attributes
    assert "samesite=lax" in attributes


async def test_production_cookie_uses_host_prefix_and_is_secure(tmp_path: Path) -> None:
    h = await build_harness(tmp_path, environment="production")
    try:
        response = await h.client.get(f"{API}/session")
        assert response.status_code == 200
        cookie = next(
            v
            for v in response.headers.get_list("set-cookie")
            if v.startswith("__Host-calendar_session=")
        )
        attributes = {part.strip().lower() for part in cookie.split(";")}
        assert {"httponly", "secure", "path=/", "samesite=lax"} <= attributes
    finally:
        await h.close()


MUTATIONS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", "/google/authorize", None),
    ("POST", "/apple/connect", APPLE_BODY),
    ("DELETE", "/apple", None),
    ("POST", "/google/parse", PARSE_BODY),
    ("POST", "/import", IMPORT_BODY),
]


@pytest.mark.parametrize("variant", ["missing-token", "wrong-token", "cross-origin"])
@pytest.mark.parametrize(("method", "path", "body"), MUTATIONS)
async def test_mutations_reject_missing_wrong_or_cross_origin_requests(
    harness: Harness, method: str, path: str, body: dict[str, Any] | None, variant: str
) -> None:
    browser = await open_browser(harness)
    headers = {
        "missing-token": {"Origin": ORIGIN},
        "wrong-token": {"X-CSRF-Token": "not-the-token", "Origin": ORIGIN},
        "cross-origin": {"X-CSRF-Token": browser.csrf, "Origin": "https://evil.example"},
    }[variant]
    response = await harness.client.request(
        method, f"{API}{path}", json=body, headers=headers, cookies=cookies(harness, browser)
    )
    assert response.status_code == 403
    assert detail(response)["code"] == "calendar_forbidden"


async def test_rejected_google_authorize_stores_no_oauth_state(harness: Harness) -> None:
    browser = await open_browser(harness)
    response = await harness.client.post(
        f"{API}/google/authorize", headers={"Origin": ORIGIN}, cookies=cookies(harness, browser)
    )
    assert response.status_code == 403
    assert (await sql(harness, "SELECT COUNT(*) FROM calendar_oauth_states"))[0][0] == 0


async def test_expired_browser_session_is_rejected(harness: Harness) -> None:
    browser = await open_browser(harness)
    await sql(harness, "UPDATE calendar_browser_sessions SET expires_at = 0")
    response = await get_as(harness, browser, "/google/calendars")
    assert response.status_code == 401


# --- Ownership -----------------------------------------------------------------------------


async def test_other_browser_cannot_read_or_disconnect_owner_connection(harness: Harness) -> None:
    use_apple(harness)
    owner = await open_browser(harness)
    other = await open_browser(harness)
    assert (await post_as(harness, owner, "/apple/connect", APPLE_BODY)).status_code == 200

    denied = await get_as(harness, other, "/apple/calendars")
    assert denied.status_code == 401
    assert APPLE_EMAIL not in denied.text

    assert (await delete_as(harness, other, "/apple")).status_code == 204
    assert await connection_count(harness) == 1

    still = await get_as(harness, owner, "/apple/calendars")
    assert still.status_code == 200
    assert {c["id"] for c in still.json()["calendars"]} == {WORK_PATH, FALLBACK_PATH}


async def test_credentials_cannot_be_moved_to_another_browser_session(harness: Harness) -> None:
    use_apple(harness)
    owner = await open_browser(harness)
    other = await open_browser(harness)
    assert (await post_as(harness, owner, "/apple/connect", APPLE_BODY)).status_code == 200
    owner_ciphertext = (
        await sql(harness, "SELECT credentials_ciphertext FROM calendar_connections")
    )[0][0]
    assert (await post_as(harness, other, "/apple/connect", APPLE_BODY)).status_code == 200

    rows = await sql(harness, "SELECT session_id, credentials_ciphertext FROM calendar_connections")
    other_session = next(
        session_id for session_id, ciphertext in rows if ciphertext != owner_ciphertext
    )
    await sql(
        harness,
        "UPDATE calendar_connections SET credentials_ciphertext = :ciphertext "
        "WHERE session_id = :session_id",
        ciphertext=owner_ciphertext,
        session_id=other_session,
    )

    moved = await get_as(harness, other, "/apple/calendars")
    assert moved.status_code == 401
    assert (await get_as(harness, owner, "/apple/calendars")).status_code == 200


# --- Google OAuth --------------------------------------------------------------------------


async def test_google_authorize_returns_state_bound_pkce_url(harness: Harness) -> None:
    browser = await open_browser(harness)
    response = await post_as(harness, browser, "/google/authorize")
    assert response.status_code == 200
    url = response.json()["authorization_url"]
    assert url.startswith(f"{AUTHORIZATION_ENDPOINT}?")
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == ["google-client-id"]
    assert query["redirect_uri"] == [GOOGLE_REDIRECT]
    assert query["code_challenge_method"] == ["S256"]
    assert CALENDAR_READ_SCOPE in query["scope"][0].split()
    state = query["state"][0]
    assert len(state) >= 32
    # Only the hash of the state is stored.
    stored = await sql(harness, "SELECT state_hash, verifier_ciphertext FROM calendar_oauth_states")
    assert len(stored) == 1
    assert state not in stored[0][0]
    assert state not in stored[0][1]


async def test_google_callback_connects_once_and_redirects_to_calendars_page(
    harness: Harness,
) -> None:
    use_google(harness)
    browser = await open_browser(harness)
    state = await google_state(harness, browser)
    params = {"state": state, "code": GOOGLE_CODE}

    first = await harness.client.get(
        f"{API}/google/callback", params=params, cookies=cookies(harness, browser)
    )
    assert first.status_code == 303
    assert first.headers["location"] == f"{FRONTEND}/calendars?calendar=google&status=connected"

    replay = await harness.client.get(
        f"{API}/google/callback", params=params, cookies=cookies(harness, browser)
    )
    assert replay.status_code == 403


async def test_google_callback_state_is_bound_to_the_starting_browser(harness: Harness) -> None:
    use_google(harness)
    owner = await open_browser(harness)
    other = await open_browser(harness)
    state = await google_state(harness, owner)
    params = {"state": state, "code": GOOGLE_CODE}

    stolen = await harness.client.get(
        f"{API}/google/callback", params=params, cookies=cookies(harness, other)
    )
    assert stolen.status_code == 403
    assert await connection_count(harness) == 0

    # The rejected attempt must not consume the state; the owner can still finish.
    owned = await harness.client.get(
        f"{API}/google/callback", params=params, cookies=cookies(harness, owner)
    )
    assert owned.status_code == 303
    assert owned.headers["location"].endswith("status=connected")
    assert await connection_count(harness) == 1


async def test_google_callback_denied_cancels_and_consumes_state(harness: Harness) -> None:
    use_google(harness)
    browser = await open_browser(harness)
    state = await google_state(harness, browser)

    denied = await harness.client.get(
        f"{API}/google/callback",
        params={"state": state, "error": "access_denied"},
        cookies=cookies(harness, browser),
    )
    assert denied.status_code == 303
    assert denied.headers["location"] == f"{FRONTEND}/?calendar=google&status=cancelled"
    assert await connection_count(harness) == 0

    replay = await harness.client.get(
        f"{API}/google/callback",
        params={"state": state, "code": GOOGLE_CODE},
        cookies=cookies(harness, browser),
    )
    assert replay.status_code == 403


async def test_google_callback_rejects_expired_state(harness: Harness) -> None:
    use_google(harness)
    browser = await open_browser(harness)
    state = await google_state(harness, browser)
    await sql(harness, "UPDATE calendar_oauth_states SET expires_at = 0")

    response = await harness.client.get(
        f"{API}/google/callback",
        params={"state": state, "code": GOOGLE_CODE},
        cookies=cookies(harness, browser),
    )
    assert response.status_code == 403
    assert await connection_count(harness) == 0


async def test_google_callback_without_browser_session_is_rejected(harness: Harness) -> None:
    use_google(harness)
    browser = await open_browser(harness)
    state = await google_state(harness, browser)
    response = await harness.client.get(
        f"{API}/google/callback", params={"state": state, "code": GOOGLE_CODE}
    )
    assert response.status_code in {401, 403}
    assert await connection_count(harness) == 0


async def test_google_credentials_are_encrypted_at_rest(harness: Harness) -> None:
    use_google(harness)
    browser = await open_browser(harness)
    await connect_google(harness, browser)

    rows = await sql(harness, "SELECT account, credentials_ciphertext FROM calendar_connections")
    assert len(rows) == 1
    account, ciphertext = rows[0]
    assert account == GOOGLE_EMAIL
    for secret in (GOOGLE_ACCESS, GOOGLE_REFRESH, GOOGLE_CLIENT_SECRET, browser.cookie):
        assert secret not in ciphertext
    session_rows = await sql(harness, "SELECT id, csrf_token FROM calendar_browser_sessions")
    assert all(browser.cookie not in str(value) for row in session_rows for value in row)

    decrypted = json.loads(Fernet(harness.key.encode()).decrypt(ciphertext.encode()))
    assert decrypted["values"]["access_token"] == GOOGLE_ACCESS
    assert decrypted["values"]["refresh_token"] == GOOGLE_REFRESH


async def test_google_disconnect_removes_stored_credentials(harness: Harness) -> None:
    use_google(harness)
    browser = await open_browser(harness)
    await connect_google(harness, browser)
    assert await connection_count(harness) == 1

    assert (await delete_as(harness, browser, "/google")).status_code == 204
    assert await connection_count(harness) == 0
    assert (await get_as(harness, browser, "/google/calendars")).status_code == 401


# --- Google calendars and parsing ----------------------------------------------------------


async def test_google_calendar_list_follows_pages_and_keeps_readable_roles(
    harness: Harness,
) -> None:
    use_google(harness)
    browser = await open_browser(harness)
    await connect_google(harness, browser)

    response = await get_as(harness, browser, "/google/calendars")
    assert response.status_code == 200
    calendars = response.json()["calendars"]
    assert [c["id"] for c in calendars] == [
        "work@example.com",
        "holidays@group.v.calendar.google.com",
        "shared@example.com",
    ]
    assert calendars[0]["primary"] is True
    assert calendars[0]["timezone"] == "America/New_York"
    list_requests = [
        r for r in harness.upstream.requests if r.url.path.endswith("/users/me/calendarList")
    ]
    assert len(list_requests) == 2


async def test_google_parse_converts_timed_and_all_day_events_with_namespaced_ids(
    harness: Harness,
) -> None:
    use_google(harness)
    browser = await open_browser(harness)
    await connect_google(harness, browser)

    response = await post_as(harness, browser, "/google/parse", PARSE_BODY)
    assert response.status_code == 200
    events = response.json()["events"]
    encoded = quote("work@example.com", safe="")
    assert [e["id"] for e in events] == [
        f"google:{encoded}:evt-timed_2025-01-06T19:00:00+00:00",
        f"google:{encoded}:evt-allday_2025-01-20",
    ]
    timed, all_day = events
    assert timed["provider"] == "google"
    assert timed["calendar_id"] == "work@example.com"
    assert timed["calendar_name"] == "Work"
    assert timed["title"] == "Lab"
    assert timed["location"] == "Room 1"
    assert timed["all_day"] is False
    assert timed["duration_hours"] == 1.5
    assert datetime.fromisoformat(timed["start"]) == datetime(2025, 1, 6, 14, tzinfo=NEW_YORK)
    assert datetime.fromisoformat(timed["end"]) == datetime(2025, 1, 6, 15, 30, tzinfo=NEW_YORK)

    assert all_day["all_day"] is True
    assert all_day["title"] == "Holiday"
    assert datetime.fromisoformat(all_day["start"]) == datetime(2025, 1, 20, tzinfo=NEW_YORK)
    assert datetime.fromisoformat(all_day["end"]) == datetime(2025, 1, 21, tzinfo=NEW_YORK)

    event_requests = [r for r in harness.upstream.requests if r.url.path.endswith("/events")]
    assert len(event_requests) == 2  # both event pages were read


async def test_google_parse_rejects_calendar_not_in_live_list(harness: Harness) -> None:
    use_google(harness)
    browser = await open_browser(harness)
    await connect_google(harness, browser)

    response = await post_as(
        harness, browser, "/google/parse", {**WINDOW, "calendar_ids": ["secret@example.com"]}
    )
    assert response.status_code == 403
    assert not [r for r in harness.upstream.requests if "secret" in r.url.path]


async def test_other_browser_cannot_list_or_parse_owner_google_calendars(harness: Harness) -> None:
    use_google(harness)
    owner = await open_browser(harness)
    other = await open_browser(harness)
    await connect_google(harness, owner)

    assert (await get_as(harness, other, "/google/calendars")).status_code == 401
    assert (await post_as(harness, other, "/google/parse", PARSE_BODY)).status_code == 401
    assert not [r for r in harness.upstream.requests if r.url.path.endswith("/events")]


# --- Apple ---------------------------------------------------------------------------------


async def test_apple_connect_rejects_non_app_password_without_echo(harness: Harness) -> None:
    use_apple(harness)
    browser = await open_browser(harness)
    response = await post_as(
        harness, browser, "/apple/connect", {"email": APPLE_EMAIL, "app_password": "hunter2"}
    )
    assert response.status_code == 400
    assert "hunter2" not in response.text
    assert await connection_count(harness) == 0
    assert not harness.upstream.requests


async def test_apple_connect_rejects_wrong_password_without_echo(harness: Harness) -> None:
    use_apple(harness)
    browser = await open_browser(harness)
    response = await post_as(
        harness,
        browser,
        "/apple/connect",
        {"email": APPLE_EMAIL, "app_password": WRONG_APPLE_PASSWORD},
    )
    assert response.status_code == 401
    assert WRONG_APPLE_PASSWORD not in response.text
    assert await connection_count(harness) == 0


async def test_apple_validation_error_does_not_echo_password(harness: Harness) -> None:
    browser = await open_browser(harness)
    response = await post_as(
        harness, browser, "/apple/connect", {"email": "x", "app_password": APPLE_PASSWORD}
    )
    assert response.status_code == 422
    assert APPLE_PASSWORD not in response.text


async def test_apple_discovery_lists_event_calendars_and_parses_recurrences(
    harness: Harness,
) -> None:
    use_apple(harness)
    browser = await open_browser(harness)
    assert (await post_as(harness, browser, "/apple/connect", APPLE_BODY)).status_code == 200

    listed = await get_as(harness, browser, "/apple/calendars")
    assert listed.status_code == 200
    calendars = {c["id"]: c for c in listed.json()["calendars"]}
    assert set(calendars) == {WORK_PATH, FALLBACK_PATH}
    assert calendars[WORK_PATH]["name"] == "Work"
    assert calendars[WORK_PATH]["timezone"] == "America/New_York"

    parsed = await post_as(
        harness,
        browser,
        "/apple/parse",
        {
            "start": "2025-01-06",
            "end": "2025-01-13",
            "timezone": "America/New_York",
            "calendar_ids": [WORK_PATH],
        },
    )
    assert parsed.status_code == 200
    events = parsed.json()["events"]
    encoded = quote(WORK_PATH, safe="")
    # Weekly series: Jan 6 is kept; Jan 13 is replaced by the moved override at 10:00 New York.
    assert [e["title"] for e in events] == ["Standup", "Standup moved"]
    assert [e["id"] for e in events] == [
        f"apple:{encoded}:standup-1_2025-01-06T14:00:00+00:00",
        f"apple:{encoded}:standup-1_2025-01-13T15:00:00+00:00",
    ]
    assert all(e["calendar_name"] == "Work" for e in events)


async def test_apple_stores_only_encrypted_app_password(harness: Harness) -> None:
    use_apple(harness)
    browser = await open_browser(harness)
    assert (await post_as(harness, browser, "/apple/connect", APPLE_BODY)).status_code == 200
    rows = await sql(harness, "SELECT account, credentials_ciphertext FROM calendar_connections")
    assert rows[0][0] == APPLE_EMAIL
    assert APPLE_PASSWORD not in rows[0][1]
    decrypted = json.loads(Fernet(harness.key.encode()).decrypt(rows[0][1].encode()))
    assert decrypted["values"]["app_password"] == APPLE_PASSWORD


async def test_apple_parse_rejects_collection_outside_listing(harness: Harness) -> None:
    use_apple(harness)
    browser = await open_browser(harness)
    assert (await post_as(harness, browser, "/apple/connect", APPLE_BODY)).status_code == 200
    response = await post_as(
        harness,
        browser,
        "/apple/parse",
        {
            **WINDOW,
            "calendar_ids": [HOME_PATH],
        },
    )
    assert response.status_code == 403


# --- URL import ----------------------------------------------------------------------------

TEAM_FEED = """BEGIN:VCALENDAR
VERSION:2.0
X-WR-CALNAME:Team Feed
X-WR-TIMEZONE:America/New_York
BEGIN:VEVENT
UID:team-1
DTSTAMP:20250101T000000Z
DTSTART;TZID=America/New_York:20250106T090000
DTEND;TZID=America/New_York:20250106T100000
RRULE:FREQ=WEEKLY;COUNT=3
EXDATE;TZID=America/New_York:20250113T090000
SUMMARY:Team sync
END:VEVENT
END:VCALENDAR
"""


async def test_url_import_expands_recurrence_and_exdates_from_fetched_feed(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetched: list[str] = []

    async def fetch(url: str) -> icalendar.Calendar:
        fetched.append(url)
        return icalendar.Calendar.from_ical(TEAM_FEED)

    monkeypatch.setattr("app.services.calendar.fetch_calendar_feed", fetch)
    browser = await open_browser(harness)
    response = await post_as(harness, browser, "/import", IMPORT_BODY)
    assert response.status_code == 200
    assert fetched == ["https://feeds.example.com/team.ics"]
    body = response.json()
    assert body["provider"] == "url"
    events = body["events"]
    assert {e["calendar_name"] for e in events} == {"Team Feed"}
    assert [e["title"] for e in events] == ["Team sync", "Team sync"]
    assert [datetime.fromisoformat(e["start"]) for e in events] == [
        datetime(2025, 1, 6, 9, tzinfo=NEW_YORK),
        datetime(2025, 1, 20, 9, tzinfo=NEW_YORK),
    ]
    assert all(e["id"].startswith("url:") for e in events)


async def test_url_import_feed_failure_returns_upstream_error_without_events(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fetch(url: str) -> icalendar.Calendar:
        raise CalendarError("upstream", "The calendar feed could not be downloaded.")

    monkeypatch.setattr("app.services.calendar.fetch_calendar_feed", fetch)
    browser = await open_browser(harness)
    response = await post_as(harness, browser, "/import", IMPORT_BODY)
    assert response.status_code == 502
    assert detail(response)["code"] == "calendar_upstream"
    assert "events" not in response.json()
