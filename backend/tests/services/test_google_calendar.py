import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
import icalendar
import pytest

from app.schemas.calendar import CalendarInfo
from app.services.calendar_errors import CalendarError
from app.services.google_calendar import GoogleCalendarProvider
from hellweek.parse import expand_events

Handler = Callable[[httpx.Request], httpx.Response]

VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CLIENT_SECRET = "gsecret-value-123"
ACCESS = "ya29.access-token-abc"
NEW_ACCESS = "ya29.new-access-token"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
NY = ZoneInfo("America/New_York")


def provider(http: httpx.AsyncClient) -> GoogleCalendarProvider:
    return GoogleCalendarProvider(
        http,
        client_id="client-id",
        client_secret=CLIENT_SECRET,
        redirect_uri="http://localhost/callback",
    )


def make_client(respond: Handler, seen: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return respond(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def json_response(payload: object, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def fresh_creds() -> dict[str, str]:
    return {
        "access_token": ACCESS,
        "expires_at": str(int(time.time()) + 3600),
        "refresh_token": "rt-1",
        "account": "student@example.com",
    }


def expired_creds() -> dict[str, str]:
    return {**fresh_creds(), "expires_at": "0"}


def refresh_payload(rotated: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "access_token": NEW_ACCESS,
        "expires_in": 3599,
        "token_type": "Bearer",
    }
    if rotated is not None:
        payload["refresh_token"] = rotated
    return payload


def timed_event(event_id: str, start: str, end: str, **extra: object) -> dict[str, object]:
    return {
        "id": event_id,
        "status": "confirmed",
        "summary": f"Event {event_id}",
        "start": {"dateTime": start},
        "end": {"dateTime": end},
        **extra,
    }


def is_token_request(request: httpx.Request) -> bool:
    return request.url.host == "oauth2.googleapis.com"


async def test_authorization_url_uses_pkce_and_read_only_scope() -> None:
    seen: list[httpx.Request] = []
    async with make_client(lambda r: json_response({}), seen) as http:
        url = provider(http).authorization_url("state-1", VERIFIER)

    query = parse_qs(urlsplit(url).query)
    # RFC 7636 appendix B test vector.
    assert query["code_challenge"] == ["E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == [f"openid email {CALENDAR_SCOPE}"]
    assert query["state"] == ["state-1"]
    assert "client_secret" not in url
    assert seen == []


@pytest.mark.parametrize(
    "verifier", ["short", "x" * 129, "bad verifier with spaces and !!!!!!!!!!!!!"]
)
async def test_authorization_url_rejects_malformed_verifier(verifier: str) -> None:
    async with make_client(lambda r: json_response({}), []) as http:
        with pytest.raises(CalendarError) as exc:
            provider(http).authorization_url("state-1", verifier)
    assert exc.value.kind == "invalid_request"


async def test_exchange_code_sends_secret_in_form_and_stores_tokens() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if is_token_request(request):
            return json_response(
                {
                    "access_token": ACCESS,
                    "expires_in": 3599,
                    "refresh_token": "rt-1",
                    "scope": f"openid email {CALENDAR_SCOPE}",
                    "token_type": "Bearer",
                }
            )
        return json_response({"email": "student@example.com"})

    async with make_client(respond, seen) as http:
        creds = await provider(http).exchange_code("auth-code", VERIFIER)

    token_request, userinfo_request = seen
    form = parse_qs(token_request.content.decode())
    assert form["grant_type"] == ["authorization_code"]
    assert form["code_verifier"] == [VERIFIER]
    assert form["client_secret"] == [CLIENT_SECRET]
    assert CLIENT_SECRET not in str(token_request.url)
    assert userinfo_request.headers["Authorization"] == f"Bearer {ACCESS}"
    assert creds["access_token"] == ACCESS
    assert creds["refresh_token"] == "rt-1"
    assert creds["account"] == "student@example.com"
    assert float(creds["expires_at"]) > time.time()


async def test_exchange_code_without_calendar_scope_is_forbidden() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if is_token_request(request):
            return json_response(
                {"access_token": ACCESS, "expires_in": 3599, "scope": "openid email"}
            )
        return json_response({"email": "student@example.com"})

    async with make_client(respond, []) as http:
        with pytest.raises(CalendarError) as exc:
            await provider(http).exchange_code("auth-code", VERIFIER)
    assert exc.value.kind == "forbidden"
    assert ACCESS not in str(exc.value)
    assert CLIENT_SECRET not in str(exc.value)


@pytest.mark.parametrize(
    ("rotated", "expected_refresh"),
    [(None, "rt-1"), ("rt-2", "rt-2")],
)
async def test_refresh_keeps_or_rotates_refresh_token(
    rotated: str | None, expected_refresh: str
) -> None:
    seen: list[httpx.Request] = []
    creds = expired_creds()
    original = dict(creds)

    def respond(request: httpx.Request) -> httpx.Response:
        if is_token_request(request):
            return json_response(refresh_payload(rotated))
        assert request.headers["Authorization"] == f"Bearer {NEW_ACCESS}"
        return json_response({"items": []})

    async with make_client(respond, seen) as http:
        _, updated = await provider(http).list_calendars(creds)

    form = parse_qs(seen[0].content.decode())
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == ["rt-1"]
    assert updated["access_token"] == NEW_ACCESS
    assert updated["refresh_token"] == expected_refresh
    assert creds == original


async def test_invalid_grant_on_refresh_is_unauthorized_without_leaking() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if is_token_request(request):
            return json_response(
                {"error": "invalid_grant", "error_description": "Bad rt-1 token"}, status=400
            )
        raise AssertionError("API must not be called after a failed refresh")

    async with make_client(respond, []) as http:
        with pytest.raises(CalendarError) as exc:
            await provider(http).list_calendars(expired_creds())
    assert exc.value.kind == "unauthorized"
    assert "rt-1" not in str(exc.value)


async def test_list_calendars_follows_pages_and_normalizes_entries() -> None:
    seen: list[httpx.Request] = []
    page_one = {
        "items": [
            {
                "id": "me@example.com",
                "accessRole": "owner",
                "summary": "Me",
                "timeZone": "America/New_York",
                "primary": True,
            },
            {"id": "holidays@example.com", "accessRole": "freeBusyReader", "summary": "Hol"},
        ],
        "nextPageToken": "page-2",
    }
    page_two = {
        "items": [
            {
                "id": "school@group.calendar.google.com",
                "accessRole": "reader",
                "summary": "  ",
                "timeZone": "",
            }
        ]
    }

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("pageToken") == "page-2":
            return json_response(page_two)
        return json_response(page_one)

    async with make_client(respond, seen) as http:
        calendars, _ = await provider(http).list_calendars(fresh_creds())

    assert calendars == [
        CalendarInfo(id="me@example.com", name="Me", timezone="America/New_York", primary=True),
        CalendarInfo(
            id="school@group.calendar.google.com",
            name="school@group.calendar.google.com",
            timezone=None,
            primary=False,
        ),
    ]
    assert seen[1].url.params["pageToken"] == "page-2"


async def test_fetch_calendar_requests_exact_window_and_encodes_calendar_id() -> None:
    seen: list[httpx.Request] = []
    start = datetime(2026, 3, 1, tzinfo=UTC)
    end = datetime(2026, 3, 8, tzinfo=UTC)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("pageToken") == "page-2":
            return json_response(
                {"items": [timed_event("b", "2026-03-03T10:00:00Z", "2026-03-03T11:00:00Z")]}
            )
        return json_response(
            {
                "items": [timed_event("a", "2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z")],
                "nextPageToken": "page-2",
            }
        )

    async with make_client(respond, seen) as http:
        cal, _ = await provider(http).fetch_calendar(
            fresh_creds(), "team/room@example.com", start, end
        )

    first = seen[0]
    assert first.url.raw_path.startswith(
        b"/calendar/v3/calendars/team%2Froom%40example.com/events?"
    )
    assert first.url.params["timeMin"] == "2026-03-01T00:00:00Z"
    assert first.url.params["timeMax"] == "2026-03-08T00:00:00Z"
    assert first.url.params["singleEvents"] == "true"
    assert first.url.params["orderBy"] == "startTime"
    assert seen[1].url.params["pageToken"] == "page-2"
    assert len(cal.walk("VEVENT")) == 2


async def test_fetch_calendar_skips_cancelled_events_even_when_malformed() -> None:
    payload = {
        "items": [
            {"id": "gone", "status": "cancelled", "start": {}},
            timed_event("ok", "2026-03-02T10:00:00Z", "2026-03-02T11:00:00Z"),
        ]
    }
    async with make_client(lambda r: json_response(payload), []) as http:
        cal, _ = await provider(http).fetch_calendar(
            fresh_creds(),
            "primary",
            datetime(2026, 3, 1, tzinfo=UTC),
            datetime(2026, 3, 8, tzinfo=UTC),
        )
    events = cal.walk("VEVENT")
    assert [str(e["UID"]) for e in events] == ["ok"]


async def test_fall_back_ambiguous_times_survive_round_trip_and_parse() -> None:
    # 2026-11-01 01:30 happens twice in New York: once at -04:00 and again at -05:00.
    payload = {
        "items": [
            timed_event("first", "2026-11-01T01:30:00-04:00", "2026-11-01T02:00:00-04:00"),
            timed_event("second", "2026-11-01T01:30:00-05:00", "2026-11-01T02:00:00-05:00"),
            {
                "id": "holiday",
                "status": "confirmed",
                "summary": "Holiday",
                "start": {"date": "2026-11-01"},
                "end": {"date": "2026-11-02"},
            },
        ]
    }
    async with make_client(lambda r: json_response(payload), []) as http:
        cal, _ = await provider(http).fetch_calendar(
            fresh_creds(),
            "primary",
            datetime(2026, 10, 31, tzinfo=UTC),
            datetime(2026, 11, 2, tzinfo=UTC),
        )

    reread = icalendar.Calendar.from_ical(cal.to_ical())
    events = expand_events(reread, date(2026, 10, 31), date(2026, 11, 2), NY)
    timed = sorted((e for e in events if not e.all_day), key=lambda e: e.start)
    assert [e.start.astimezone(UTC) for e in timed] == [
        datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
        datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
    ]
    all_day = [e for e in events if e.all_day]
    assert [e.title for e in all_day] == ["Holiday"]


@pytest.mark.parametrize(
    "item",
    [
        {"id": "no-start", "end": {"dateTime": "2026-03-02T11:00:00Z"}},
        {
            "id": "naive",
            "start": {"dateTime": "2026-03-02T10:00:00"},
            "end": {"dateTime": "2026-03-02T11:00:00Z"},
        },
        timed_event("backwards", "2026-03-02T11:00:00Z", "2026-03-02T10:00:00Z"),
        {
            "id": "mixed",
            "start": {"date": "2026-03-02"},
            "end": {"dateTime": "2026-03-02T11:00:00Z"},
        },
    ],
)
async def test_malformed_active_events_raise_upstream(item: dict[str, object]) -> None:
    payload = {"items": [item]}
    async with make_client(lambda r: json_response(payload), []) as http:
        with pytest.raises(CalendarError) as exc:
            await provider(http).fetch_calendar(
                fresh_creds(),
                "primary",
                datetime(2026, 3, 1, tzinfo=UTC),
                datetime(2026, 3, 8, tzinfo=UTC),
            )
    assert exc.value.kind == "upstream"


async def test_401_refreshes_once_and_retries_with_new_token() -> None:
    seen: list[httpx.Request] = []
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if is_token_request(request):
            return json_response(refresh_payload("rt-1"))
        calls += 1
        if request.headers["Authorization"] == f"Bearer {ACCESS}":
            return json_response({"error": {"code": 401}}, status=401)
        return json_response({"items": []})

    async with make_client(respond, seen) as http:
        _, updated = await provider(http).list_calendars(fresh_creds())

    assert calls == 2
    assert updated["access_token"] == NEW_ACCESS


async def test_second_401_after_refresh_is_unauthorized() -> None:
    api_calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls
        if is_token_request(request):
            return json_response(refresh_payload())
        api_calls += 1
        return json_response({"error": {"code": 401}}, status=401)

    async with make_client(respond, []) as http:
        with pytest.raises(CalendarError) as exc:
            await provider(http).list_calendars(fresh_creds())
    assert exc.value.kind == "unauthorized"
    assert api_calls == 2
    assert ACCESS not in str(exc.value)
    assert NEW_ACCESS not in str(exc.value)


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}}, "forbidden"),
        (403, {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}, "upstream"),
        (404, {}, "invalid_request"),
        (503, {}, "upstream"),
    ],
)
async def test_api_error_statuses_map_to_safe_kinds(
    status: int, body: dict[str, object], kind: str
) -> None:
    async with make_client(lambda r: json_response(body, status=status), []) as http:
        with pytest.raises(CalendarError) as exc:
            await provider(http).list_calendars(fresh_creds())
    assert exc.value.kind == kind
    assert ACCESS not in str(exc.value)


async def test_read_timeout_maps_to_timeout() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async with make_client(respond, []) as http:
        with pytest.raises(CalendarError) as exc:
            await provider(http).list_calendars(fresh_creds())
    assert exc.value.kind == "timeout"


async def test_unconfigured_provider_fails_before_any_request() -> None:
    seen: list[httpx.Request] = []
    async with make_client(lambda r: json_response({}), seen) as http:
        unconfigured = GoogleCalendarProvider(
            http, client_id="", client_secret=CLIENT_SECRET, redirect_uri="http://localhost/cb"
        )
        with pytest.raises(CalendarError) as exc:
            await unconfigured.list_calendars(fresh_creds())
    assert exc.value.kind == "not_configured"
    assert seen == []
