import base64
from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.services.apple_calendar import BASE_URL, HOME_URL_KEY, AppleCalendarProvider
from app.services.calendar_errors import CalendarError

USERNAME = "person@icloud.com"
PASSWORD = "abcd-efgh-ijkl-mnop"
CREDS = {"username": USERNAME, "app_password": PASSWORD}
PRINCIPAL_PATH = "/123456789/principal/"
HOME_PATH = "/123456789/calendars/"
HOME_URL = f"https://caldav.icloud.com{HOME_PATH}"
WORK_PATH = "/123456789/calendars/work-uuid/"
START = datetime(2025, 1, 1, tzinfo=ZoneInfo("America/New_York"))
END = datetime(2025, 2, 1, tzinfo=UTC)

Respond = Callable[[httpx.Request], httpx.Response]


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
    "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTIMEZONE\nTZID:America/New_York\n"
    "BEGIN:STANDARD\nDTSTART:19701101T020000\nTZOFFSETFROM:-0400\nTZOFFSETTO:-0500\n"
    "END:STANDARD\nEND:VTIMEZONE\nEND:VCALENDAR"
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
        _listing_entry(WORK_PATH, name="Work", timezone=VTIMEZONE),
        _listing_entry("/123456789/calendars/fallback-uuid/"),
        _listing_entry("/123456789/calendars/tasks-uuid/", components='<C:comp name="VTODO"/>'),
        _listing_entry("/123456789/calendars/inbox/", resource="<D:collection/>", components=None),
        _listing_entry(f"{WORK_PATH}nested/", name="Nested"),
    ]
)

EVENT_1 = "\n".join(
    [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Apple Inc.//iCal//EN",
        "BEGIN:VTIMEZONE",
        "TZID:America/New_York",
        "BEGIN:STANDARD",
        "DTSTART:19701101T020000",
        "TZOFFSETFROM:-0400",
        "TZOFFSETTO:-0500",
        "END:STANDARD",
        "END:VTIMEZONE",
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
OVERRIDE = "\n".join(
    [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "BEGIN:VTIMEZONE",
        "TZID:America/New_York",
        "BEGIN:STANDARD",
        "DTSTART:19701101T020000",
        "TZOFFSETFROM:-0400",
        "TZOFFSETTO:-0500",
        "END:STANDARD",
        "END:VTIMEZONE",
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


REPORT_BODY = _report_entry(f"{WORK_PATH}standup-1.ics", EVENT_1) + _report_entry(
    f"{WORK_PATH}standup-1-override.ics", OVERRIDE
)


def _route(request: httpx.Request, *, report: Respond | None = None) -> httpx.Response:
    if request.method == "REPORT":
        return report(request) if report is not None else _xml(REPORT_BODY)
    path = request.url.path
    if path == "/":
        return _xml(PRINCIPAL_BODY)
    if path == PRINCIPAL_PATH:
        return _xml(HOME_SET_BODY)
    if path == HOME_PATH:
        return _xml(LISTING_BODY)
    return httpx.Response(404)


def _http(handler: Respond, seen: list[httpx.Request]) -> httpx.AsyncClient:
    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(record))


async def test_list_calendars_keeps_only_direct_event_collections() -> None:
    seen: list[httpx.Request] = []
    original = dict(CREDS)
    async with _http(_route, seen) as http:
        calendars, updated = await AppleCalendarProvider(http).list_calendars(CREDS)

    assert [(c.id, c.name, c.timezone, c.primary) for c in calendars] == [
        (WORK_PATH, "Work", "America/New_York", False),
        ("/123456789/calendars/fallback-uuid/", "fallback-uuid", None, False),
    ]
    assert [(r.method, r.url.path) for r in seen] == [
        ("PROPFIND", "/"),
        ("PROPFIND", PRINCIPAL_PATH),
        ("PROPFIND", HOME_PATH),
    ]
    assert updated == {**original, HOME_URL_KEY: HOME_URL}
    assert CREDS == original
    expected_auth = "Basic " + base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    assert all(r.headers["Authorization"] == expected_auth for r in seen)
    assert all(PASSWORD not in str(r.url) for r in seen)


async def test_fetch_calendar_keeps_overrides_and_merges_timezones_once() -> None:
    seen: list[httpx.Request] = []
    async with _http(_route, seen) as http:
        calendar, updated = await AppleCalendarProvider(http).fetch_calendar(
            CREDS, WORK_PATH, START, END
        )

    events = list(calendar.walk("VEVENT"))
    assert len(events) == 2
    assert any(str(e.get("SUMMARY")) == "Standup" and e.get("RRULE") for e in events)
    assert any(e.get("RECURRENCE-ID") is not None for e in events)
    assert len(list(calendar.walk("VTIMEZONE"))) == 1
    report = seen[-1]
    assert report.method == "REPORT"
    assert report.headers["Depth"] == "1"
    body = report.content.decode()
    assert 'start="20250101T050000Z"' in body
    assert 'end="20250201T000000Z"' in body
    assert updated[HOME_URL_KEY] == HOME_URL


async def test_fetch_uses_valid_cached_home_without_discovery() -> None:
    seen: list[httpx.Request] = []
    creds = {**CREDS, HOME_URL_KEY: HOME_URL}
    async with _http(_route, seen) as http:
        await AppleCalendarProvider(http).fetch_calendar(creds, WORK_PATH, START, END)

    assert [r.method for r in seen] == ["REPORT"]


async def test_fetch_rediscovers_when_cached_home_is_untrusted() -> None:
    seen: list[httpx.Request] = []
    creds = {**CREDS, HOME_URL_KEY: "https://evil.example/calendars/"}
    async with _http(_route, seen) as http:
        await AppleCalendarProvider(http).fetch_calendar(creds, WORK_PATH, START, END)

    assert seen[0].url == httpx.URL(BASE_URL)


async def test_same_provider_redirect_is_followed_manually() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "caldav.icloud.com" and request.url.path == "/":
            return httpx.Response(301, headers={"Location": "https://p55-caldav.icloud.com/"})
        return _route(request)

    async with _http(handler, seen) as http:
        calendars, _ = await AppleCalendarProvider(http).list_calendars(CREDS)

    assert [c.id for c in calendars] == [WORK_PATH, "/123456789/calendars/fallback-uuid/"]
    assert seen[1].url.host == "p55-caldav.icloud.com"


@pytest.mark.parametrize(
    "location",
    [
        "https://evil.example/",
        "http://caldav.icloud.com/",
        "https://caldav.icloud.com:8443/",
        "https://user:secret@caldav.icloud.com/",
        "https://caldav.icloud.com.evil.example/",
    ],
)
async def test_offsite_or_unsafe_redirect_is_rejected_before_sending_credentials(
    location: str,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": location})

    async with _http(handler, seen) as http:
        with pytest.raises(CalendarError) as exc:
            await AppleCalendarProvider(http).list_calendars(CREDS)

    assert exc.value.kind == "upstream"
    assert len(seen) == 1


async def test_redirect_loop_stops_after_bounded_hops() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "/loop/"})

    async with _http(handler, seen) as http:
        with pytest.raises(CalendarError) as exc:
            await AppleCalendarProvider(http).list_calendars(CREDS)

    assert exc.value.kind == "upstream"
    assert len(seen) == 6


@pytest.mark.parametrize(
    "href",
    [
        "https://evil.example/123456789/principal/",
        "//evil.example/123456789/principal/",
        "/123456789/%2e%2e/principal/",
    ],
)
async def test_untrusted_principal_href_is_rejected_before_second_request(href: str) -> None:
    seen: list[httpx.Request] = []
    principal = PRINCIPAL_BODY.replace(PRINCIPAL_PATH, href)

    def handler(request: httpx.Request) -> httpx.Response:
        return _xml(principal) if request.url.path == "/" else _route(request)

    async with _http(handler, seen) as http:
        with pytest.raises(CalendarError) as exc:
            await AppleCalendarProvider(http).list_calendars(CREDS)

    assert exc.value.kind == "upstream"
    assert len(seen) == 1


async def test_principal_denied_by_propstat_is_upstream() -> None:
    denied = (
        "<D:response><D:href>/</D:href><D:propstat><D:prop><D:current-user-principal/></D:prop>"
        "<D:status>HTTP/1.1 403 Forbidden</D:status></D:propstat></D:response>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return _xml(denied) if request.url.path == "/" else _route(request)

    async with _http(handler, []) as http:
        with pytest.raises(CalendarError) as exc:
            await AppleCalendarProvider(http).list_calendars(CREDS)

    assert exc.value.kind == "upstream"


async def test_unauthenticated_principal_is_unauthorized() -> None:
    body = (
        "<D:response><D:href>/</D:href><D:propstat><D:prop><D:current-user-principal>"
        "<D:unauthenticated/></D:current-user-principal></D:prop>"
        "<D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return _xml(body) if request.url.path == "/" else _route(request)

    async with _http(handler, []) as http:
        with pytest.raises(CalendarError) as exc:
            await AppleCalendarProvider(http).list_calendars(CREDS)

    assert exc.value.kind == "unauthorized"


@pytest.mark.parametrize(
    ("status", "expected_kind"),
    [(401, "unauthorized"), (403, "forbidden"), (503, "upstream")],
)
async def test_listing_http_status_maps_to_error_kind(status: int, expected_kind: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == HOME_PATH:
            return httpx.Response(status)
        return _route(request)

    async with _http(handler, []) as http:
        with pytest.raises(CalendarError) as exc:
            await AppleCalendarProvider(http).list_calendars(CREDS)

    assert exc.value.kind == expected_kind
    assert PASSWORD not in str(exc.value)


def _raise_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("slow", request=request)


def _raise_connect(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


def _limited(_: httpx.Request) -> httpx.Response:
    return httpx.Response(
        403,
        content=b'<D:error xmlns:D="DAV:"><C:number-of-matches-within-limits '
        b'xmlns:C="urn:ietf:params:xml:ns:caldav"/></D:error>',
    )


def _multistatus_status(status: str) -> Respond:
    body = (
        f"<D:response><D:href>{WORK_PATH}standup-1.ics</D:href>"
        f"<D:status>{status}</D:status></D:response>"
    )
    return lambda _: _xml(body)


REPORT_FAILURES: list[tuple[str, Respond, str]] = [
    ("unauthorized", lambda _: httpx.Response(401), "unauthorized"),
    ("forbidden", lambda _: httpx.Response(403, text="<html>no</html>"), "forbidden"),
    ("limited", _limited, "upstream"),
    ("server-error", lambda _: httpx.Response(503), "upstream"),
    ("non-multistatus-200", lambda _: httpx.Response(200, text="<html/>"), "upstream"),
    ("not-xml", lambda _: httpx.Response(207, text="not xml"), "upstream"),
    (
        "wrong-root",
        lambda _: httpx.Response(207, content=b'<D:error xmlns:D="DAV:"/>'),
        "upstream",
    ),
    ("response-level-404", _multistatus_status("HTTP/1.1 404 Not Found"), "upstream"),
    (
        "calendar-data-404",
        lambda _: _xml(
            f"<D:response><D:href>{WORK_PATH}standup-1.ics</D:href><D:propstat>"
            "<D:prop><C:calendar-data/></D:prop>"
            "<D:status>HTTP/1.1 404 Not Found</D:status></D:propstat></D:response>"
        ),
        "upstream",
    ),
    (
        "missing-calendar-data",
        lambda _: _xml(
            f"<D:response><D:href>{WORK_PATH}standup-1.ics</D:href><D:propstat>"
            '<D:prop><D:getetag>"x"</D:getetag></D:prop>'
            "<D:status>HTTP/1.1 200 OK</D:status></D:propstat></D:response>"
        ),
        "upstream",
    ),
    (
        "unclosed-vevent",
        lambda _: _xml(
            _report_entry(
                f"{WORK_PATH}broken.ics",
                "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:broken",
            )
        ),
        "upstream",
    ),
    (
        "entity-expansion",
        lambda _: httpx.Response(
            207,
            content=(
                b'<?xml version="1.0"?><!DOCTYPE m [<!ENTITY a "aaaa">]>'
                b'<D:multistatus xmlns:D="DAV:">&a;</D:multistatus>'
            ),
        ),
        "upstream",
    ),
    ("read-timeout", _raise_timeout, "timeout"),
    ("connect-error", _raise_connect, "upstream"),
]


@pytest.mark.parametrize(
    ("report", "expected_kind"),
    [(report, kind) for _, report, kind in REPORT_FAILURES],
    ids=[name for name, _, _ in REPORT_FAILURES],
)
async def test_report_failures_map_to_safe_error_kinds(report: Respond, expected_kind: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _route(request, report=report)

    async with _http(handler, []) as http:
        with pytest.raises(CalendarError) as exc:
            await AppleCalendarProvider(http).fetch_calendar(CREDS, WORK_PATH, START, END)

    assert exc.value.kind == expected_kind
    assert PASSWORD not in str(exc.value)
    assert "BEGIN:" not in str(exc.value)


async def test_empty_report_is_an_empty_calendar_not_an_error() -> None:
    async with _http(lambda r: _route(r, report=lambda _: _xml("")), []) as http:
        calendar, _ = await AppleCalendarProvider(http).fetch_calendar(CREDS, WORK_PATH, START, END)

    assert list(calendar.walk("VEVENT")) == []


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2025, 1, 1), END),
        (START, datetime(2025, 1, 1)),
        (END, START),
        (START, START),
    ],
)
async def test_invalid_window_is_rejected_without_requests(start: datetime, end: datetime) -> None:
    seen: list[httpx.Request] = []
    creds = {**CREDS, HOME_URL_KEY: HOME_URL}
    async with _http(_route, seen) as http:
        with pytest.raises(CalendarError) as exc:
            await AppleCalendarProvider(http).fetch_calendar(creds, WORK_PATH, start, end)

    assert exc.value.kind == "invalid_request"
    assert seen == []


@pytest.mark.parametrize(
    "calendar_id",
    [
        "work-uuid",
        "//evil.example/123456789/calendars/work-uuid/",
        "/123456789/calendars/../work-uuid/",
        "/other/calendar/",
        f"{WORK_PATH}nested/",
    ],
)
async def test_invalid_calendar_id_is_rejected_before_report(calendar_id: str) -> None:
    seen: list[httpx.Request] = []
    creds = {**CREDS, HOME_URL_KEY: HOME_URL}
    async with _http(_route, seen) as http:
        with pytest.raises(CalendarError) as exc:
            await AppleCalendarProvider(http).fetch_calendar(creds, calendar_id, START, END)

    assert exc.value.kind == "invalid_request"
    assert seen == []


@pytest.mark.parametrize(
    "creds",
    [
        {},
        {"username": USERNAME},
        {"app_password": PASSWORD},
        {"username": "a:b@icloud.com", "app_password": PASSWORD},
        {"username": "   ", "app_password": PASSWORD},
    ],
)
async def test_incomplete_credentials_are_not_configured_without_requests(
    creds: dict[str, str],
) -> None:
    seen: list[httpx.Request] = []
    async with _http(_route, seen) as http:
        with pytest.raises(CalendarError) as exc:
            await AppleCalendarProvider(http).list_calendars(creds)

    assert exc.value.kind == "not_configured"
    assert seen == []


@pytest.mark.parametrize("segment", ["caf%C3%A9", "café", "Family%20plans"])
async def test_encoded_and_unicode_calendar_paths_preserve_recurring_events(segment: str) -> None:
    from datetime import date
    from urllib.parse import unquote

    from hellweek.parse import expand_events

    path = f"{HOME_PATH}{segment}/"

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "REPORT"
        assert request.url.path == unquote(path)
        return _xml(_report_entry(f"{path}event.ics", EVENT_1))

    async with _http(respond, []) as http:
        calendar, _ = await AppleCalendarProvider(http).fetch_calendar(
            {**CREDS, HOME_URL_KEY: HOME_URL}, path, START, END
        )
    events = expand_events(
        calendar, date(2025, 1, 1), date(2025, 1, 31), ZoneInfo("America/New_York")
    )
    assert [(event.start.day, event.start.hour, event.duration_hours) for event in events] == [
        (6, 9, 0.25),
        (13, 9, 0.25),
        (20, 9, 0.25),
        (27, 9, 0.25),
    ]
