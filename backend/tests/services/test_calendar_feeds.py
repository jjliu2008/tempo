import asyncio
import base64
import gzip
import socket
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from aiohttp import web

from app.services import calendar_feeds
from app.services.calendar_errors import CalendarError
from app.services.calendar_feeds import (
    _is_global_ip,
    _public_url,
    _PublicResolver,
    _redirect_target,
    fetch_calendar_feed,
    google_calendar_id,
)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

ICS = "\r\n".join(
    [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//test//EN",
        "BEGIN:VEVENT",
        "UID:standup-1",
        "DTSTAMP:20260101T000000Z",
        "DTSTART:20260102T090000Z",
        "DTEND:20260102T093000Z",
        "SUMMARY:Standup",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
)
MAX_BYTES = 5 * 1024 * 1024


def _oversized_ics() -> bytes:
    return ICS.replace(
        "SUMMARY:Standup", "SUMMARY:Standup\r\nDESCRIPTION:" + "x" * MAX_BYTES
    ).encode()


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Test-only resolver table. Only 127.0.0.1 counts as public so local servers can be used."""
    table: dict[str, list[str]] = {}

    async def lookup(host: str, port: int, family: int) -> list[str]:
        return table.get(host, ["127.0.0.1"])

    monkeypatch.setattr(calendar_feeds, "_system_addresses", lookup)
    monkeypatch.setattr(calendar_feeds, "_is_global_ip", lambda ip: str(ip) == "127.0.0.1")
    return table


@asynccontextmanager
async def _serve(handlers: dict[str, Handler]) -> AsyncIterator[tuple[int, list[str]]]:
    hits: list[str] = []

    @web.middleware
    async def record(request: web.Request, handler: Any) -> web.StreamResponse:
        hits.append(request.path)
        return await handler(request)

    app = web.Application(middlewares=[record])
    for path, handler in handlers.items():
        app.router.add_route("*", path, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        port = runner.addresses[0][1]
        yield port, hits
    finally:
        await runner.cleanup()


def _ics_handler(body: str = ICS) -> Handler:
    async def handler(request: web.Request) -> web.StreamResponse:
        return web.Response(body=body.encode(), content_type="text/calendar")

    return handler


def _status_handler(status: int) -> Handler:
    async def handler(request: web.Request) -> web.StreamResponse:
        return web.Response(status=status, text="denied")

    return handler


def _redirect_handler(location: str) -> Handler:
    async def handler(request: web.Request) -> web.StreamResponse:
        return web.Response(status=302, headers={"Location": location})

    return handler


def _google_cid(address: str) -> str:
    return base64.urlsafe_b64encode(address.encode()).decode()


# google_calendar_id: accepted Google web/embed links


def test_google_cid_with_padding_decodes_to_calendar_id() -> None:
    cid = _google_cid("person@gmail.com")
    assert "=" in cid
    assert google_calendar_id(f"https://calendar.google.com/calendar/embed?cid={cid}") == (
        "person@gmail.com"
    )


def test_google_cid_without_padding_decodes_to_calendar_id() -> None:
    cid = _google_cid("person@gmail.com").rstrip("=")
    assert google_calendar_id(f"https://calendar.google.com/calendar/embed?cid={cid}") == (
        "person@gmail.com"
    )


def test_google_src_holiday_id_with_encoded_hash_is_accepted() -> None:
    url = (
        "https://calendar.google.com/calendar/embed"
        "?src=en.usa%23holiday%40group.v.calendar.google.com"
    )
    assert google_calendar_id(url) == "en.usa#holiday@group.v.calendar.google.com"


def test_google_raw_email_in_cid_is_accepted() -> None:
    assert (
        google_calendar_id("https://calendar.google.com/calendar/embed?cid=person@gmail.com")
        == "person@gmail.com"
    )


def test_google_same_id_in_src_and_cid_is_accepted() -> None:
    cid = _google_cid("person@gmail.com")
    url = f"https://calendar.google.com/calendar/embed?src=person@gmail.com&cid={cid}"
    assert google_calendar_id(url) == "person@gmail.com"


def test_google_legacy_host_is_accepted() -> None:
    url = "https://www.google.com/calendar/embed?src=person@gmail.com"
    assert google_calendar_id(url) == "person@gmail.com"


@pytest.mark.parametrize(
    "url",
    [
        "https://calendar.google.com/calendar/embed?cid=!!!",
        "https://calendar.google.com/calendar/embed?cid=aGVsbG8=",
        "https://calendar.google.com/calendar/embed?src=not-an-email",
        "https://calendar.google.com/calendar/embed?src=",
        "https://calendar.google.com/calendar/embed?src=a@x.com&src=b@x.com",
        "https://calendar.google.com/calendar/event?eid=abc",
        "https://calendar.google.com/calendar/eventedit/abc",
        "https://calendar.google.com/calendar/r?eid=xyz",
        "https://calendar.google.com/calendar/r",
        "https://u@calendar.google.com/calendar/embed?src=a@b.com",
        "http://calendar.google.com/calendar/embed?src=a@b.com",
        "https://calendar.google.com:443/calendar/embed?src=a@b.com",
        "https://calendar.google.com/calendar/embed?src=a@b.com#x",
        "https://calendar.google.com/calendar\\embed?src=a@b.com",
    ],
)
def test_google_malformed_or_event_links_are_invalid_request(url: str) -> None:
    with pytest.raises(CalendarError) as exc:
        google_calendar_id(url)
    assert exc.value.kind == "invalid_request"


@pytest.mark.parametrize(
    "url",
    [
        "https://calendar.google.com/calendar/ical/person%40gmail.com/public/basic.ics",
        "webcal://calendar.google.com/calendar/ical/person%40gmail.com/public/basic.ics",
        "https://example.com/cal.ics",
        "https://calendar.google.com.evil.example/calendar/embed?src=a@b.com",
        "https://www.google.com/search?q=x",
        "not a url",
        "https://[::1/cal",
    ],
)
def test_non_google_web_links_return_none(url: str) -> None:
    assert google_calendar_id(url) is None


# _public_url: normalization and acceptance


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("webcal://Example.COM/cal.ics", "https://example.com/cal.ics"),
        ("HTTP://Example.com", "http://example.com/"),
        ("https://example.com/a?x=1", "https://example.com/a?x=1"),
        ("https://example.com:8443/cal", "https://example.com:8443/cal"),
        ("https://8.8.8.8/cal", "https://8.8.8.8/cal"),
        ("https://[2606:4700:4700::1111]/cal", "https://[2606:4700:4700::1111]/cal"),
    ],
)
def test_public_url_normalizes_safe_urls(raw: str, expected: str) -> None:
    assert _public_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://example.com/x",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "example.com/cal",
        "https:///cal",
        "https://localhost/x",
        "https://intranet.localhost/x",
        "https://intranet/x",
        "https://example.com./x",
        "https://exa_mple.com/x",
        "https://example.com/x y",
        "https://example.com/a\\b",
        "https://example.com/x#frag",
        "https://exämple.com/x",
        "https://example.com:0/x",
        "https://example.com:99999/x",
        "https://example.com:abc/x",
        "   ",
        "https://example.com/" + "a" * 8200,
    ],
)
def test_public_url_rejects_unsafe_urls(raw: str) -> None:
    with pytest.raises(CalendarError) as exc:
        _public_url(raw)
    assert exc.value.kind == "invalid_request"


def test_public_url_rejects_credentials_without_leaking_password() -> None:
    with pytest.raises(CalendarError) as exc:
        _public_url("https://user:hunter2@example.com/x")
    assert exc.value.kind == "invalid_request"
    assert "hunter2" not in str(exc.value)


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.1.1",
        "100.64.0.1",
        "224.0.0.1",
        "240.0.0.1",
        "0.0.0.0",
        "2130706433",
        "0x7f000001",
        "127.1",
        "0177.0.0.1",
    ],
)
def test_private_or_alternate_ipv4_hosts_are_rejected(ip: str) -> None:
    with pytest.raises(CalendarError) as exc:
        _public_url(f"https://{ip}/cal")
    assert exc.value.kind == "invalid_request"


@pytest.mark.parametrize(
    "ip",
    [
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "2002:7f00:1::1",
        "64:ff9b::7f00:1",
        "2001::1",
    ],
)
def test_private_or_embedded_ipv6_hosts_are_rejected(ip: str) -> None:
    with pytest.raises(CalendarError) as exc:
        _public_url(f"https://[{ip}]/cal")
    assert exc.value.kind == "invalid_request"


@pytest.mark.parametrize(
    "ip",
    ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "2002:0808:0808::1"],
)
def test_global_addresses_are_accepted(ip: str) -> None:
    import ipaddress

    assert _is_global_ip(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.1",
        "127.0.0.1",
        "100.64.0.1",
        "169.254.1.1",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "2002:7f00:1::1",
        "64:ff9b::7f00:1",
        "2001::1",
    ],
)
def test_non_global_addresses_are_refused(ip: str) -> None:
    import ipaddress

    assert _is_global_ip(ipaddress.ip_address(ip)) is False


# _PublicResolver


async def test_resolver_returns_only_global_addresses() -> None:
    async def lookup(host: str, port: int, family: int) -> list[str]:
        return ["10.0.0.1", "not-an-ip", "8.8.8.8", "8.8.8.8", "1.1.1.1"]

    results = await _PublicResolver(lookup).resolve("feed.example", 443)
    assert [result["host"] for result in results] == ["8.8.8.8", "1.1.1.1"]
    first = results[0]
    assert first["hostname"] == "feed.example"
    assert first["port"] == 443
    assert first["family"] == socket.AF_INET


async def test_resolver_refuses_when_no_global_address_remains() -> None:
    async def lookup(host: str, port: int, family: int) -> list[str]:
        return ["10.0.0.1", "192.168.0.1"]

    with pytest.raises(CalendarError) as exc:
        await _PublicResolver(lookup).resolve("feed.example", 80)
    assert exc.value.kind == "upstream"


# _redirect_target


@pytest.mark.parametrize(
    ("current", "location", "expected"),
    [
        ("http://feed.example/a", "https://feed.example/b", "https://feed.example/b"),
        ("https://feed.example/a", "/c", "https://feed.example/c"),
        ("https://feed.example/a", "webcal://feed.example/d.ics", "https://feed.example/d.ics"),
    ],
)
def test_redirect_target_accepts_safe_hops(current: str, location: str, expected: str) -> None:
    assert _redirect_target(current, location) == expected


@pytest.mark.parametrize(
    ("current", "location"),
    [
        ("https://feed.example/a", "http://feed.example/b"),
        ("https://feed.example/a", "http://10.0.0.1/b"),
        ("https://feed.example/a", "http://127.0.0.1/b"),
        ("https://feed.example/a", "ftp://feed.example/b"),
        ("https://feed.example/a", "/b\\c"),
        ("https://feed.example/a", "https://user:hunter2@feed.example/b"),
    ],
)
def test_redirect_target_rejects_unsafe_hops(current: str, location: str) -> None:
    with pytest.raises(CalendarError) as exc:
        _redirect_target(current, location)
    assert exc.value.kind == "upstream"
    assert "hunter2" not in str(exc.value)


# fetch_calendar_feed: rejections that never touch the network


async def test_fetch_refuses_google_web_link_before_network() -> None:
    with pytest.raises(CalendarError) as exc:
        await fetch_calendar_feed("https://calendar.google.com/calendar/embed?src=a@b.com")
    assert exc.value.kind == "invalid_request"


async def test_fetch_refuses_loopback_literal_before_network() -> None:
    with pytest.raises(CalendarError) as exc:
        await fetch_calendar_feed("https://127.0.0.1/")
    assert exc.value.kind == "invalid_request"


async def test_fetch_refuses_credentials_without_leaking_password() -> None:
    with pytest.raises(CalendarError) as exc:
        await fetch_calendar_feed("https://user:hunter2@example.com/feed.ics")
    assert exc.value.kind == "invalid_request"
    assert "hunter2" not in str(exc.value)


async def test_fetch_refuses_host_resolving_only_to_private_addresses(
    dns: dict[str, list[str]],
) -> None:
    dns["private.example"] = ["10.0.0.5"]
    with pytest.raises(CalendarError) as exc:
        await fetch_calendar_feed("https://private.example/feed.ics")
    assert exc.value.kind == "upstream"
    assert "private.example" not in str(exc.value)


# fetch_calendar_feed: local server behavior


async def test_fetch_parses_valid_ics(dns: dict[str, list[str]]) -> None:
    async with _serve({"/feed.ics": _ics_handler()}) as (port, hits):
        calendar = await fetch_calendar_feed(f"http://feed.example:{port}/feed.ics")
    assert hits == ["/feed.ics"]
    summaries = [str(event["SUMMARY"]) for event in calendar.walk("VEVENT")]
    assert summaries == ["Standup"]


async def test_fetch_follows_five_redirects(dns: dict[str, list[str]]) -> None:
    handlers: dict[str, Handler] = {f"/r{i}": _redirect_handler(f"/r{i + 1}") for i in range(5)}
    handlers["/r5"] = _ics_handler()
    async with _serve(handlers) as (port, hits):
        calendar = await fetch_calendar_feed(f"http://feed.example:{port}/r0")
    assert hits == ["/r0", "/r1", "/r2", "/r3", "/r4", "/r5"]
    assert [str(event["SUMMARY"]) for event in calendar.walk("VEVENT")] == ["Standup"]


async def test_fetch_refuses_sixth_redirect(dns: dict[str, list[str]]) -> None:
    handlers: dict[str, Handler] = {f"/r{i}": _redirect_handler(f"/r{i + 1}") for i in range(6)}
    handlers["/r6"] = _ics_handler()
    async with _serve(handlers) as (port, _hits):
        with pytest.raises(CalendarError) as exc:
            await fetch_calendar_feed(f"http://feed.example:{port}/r0")
    assert exc.value.kind == "upstream"
    assert "too many" in str(exc.value)


async def test_fetch_refuses_redirect_loop(dns: dict[str, list[str]]) -> None:
    handlers: dict[str, Handler] = {
        "/a": _redirect_handler("/b"),
        "/b": _redirect_handler("/a"),
    }
    async with _serve(handlers) as (port, _hits):
        with pytest.raises(CalendarError) as exc:
            await fetch_calendar_feed(f"http://feed.example:{port}/a")
    assert exc.value.kind == "upstream"
    assert "loop" in str(exc.value)


async def test_fetch_refuses_redirect_to_private_literal(dns: dict[str, list[str]]) -> None:
    handlers: dict[str, Handler] = {"/start": _redirect_handler("http://10.0.0.1/secret")}
    async with _serve(handlers) as (port, hits):
        with pytest.raises(CalendarError) as exc:
            await fetch_calendar_feed(f"http://feed.example:{port}/start")
    assert exc.value.kind == "upstream"
    assert hits == ["/start"]


async def test_fetch_refuses_redirect_to_dns_private_host(dns: dict[str, list[str]]) -> None:
    dns["private.example"] = ["10.0.0.5"]

    async def redirect(request: web.Request) -> web.StreamResponse:
        port = request.url.port
        return web.Response(
            status=302, headers={"Location": f"http://private.example:{port}/secret"}
        )

    async with _serve({"/start": redirect}) as (port, hits):
        with pytest.raises(CalendarError) as exc:
            await fetch_calendar_feed(f"http://feed.example:{port}/start")
    assert exc.value.kind == "upstream"
    assert hits == ["/start"]


@pytest.mark.parametrize(
    ("status", "kind"),
    [(401, "unauthorized"), (403, "forbidden"), (404, "invalid_request"), (500, "upstream")],
)
async def test_fetch_maps_http_status_to_error_kind(
    dns: dict[str, list[str]], status: int, kind: str
) -> None:
    async with _serve({"/feed.ics": _status_handler(status)}) as (port, _hits):
        with pytest.raises(CalendarError) as exc:
            await fetch_calendar_feed(f"http://feed.example:{port}/feed.ics")
    assert exc.value.kind == kind


async def test_fetch_refuses_html_body(dns: dict[str, list[str]]) -> None:
    html = "<html><body>Sign in</body></html>"
    async with _serve({"/feed.ics": _ics_handler(html)}) as (port, _hits):
        with pytest.raises(CalendarError) as exc:
            await fetch_calendar_feed(f"http://feed.example:{port}/feed.ics")
    assert exc.value.kind == "upstream"


async def test_fetch_refuses_non_utf8_body(dns: dict[str, list[str]]) -> None:
    async def handler(request: web.Request) -> web.StreamResponse:
        return web.Response(body=b"\xff\xfeBEGIN:VCALENDAR")

    async with _serve({"/feed.ics": handler}) as (port, _hits):
        with pytest.raises(CalendarError) as exc:
            await fetch_calendar_feed(f"http://feed.example:{port}/feed.ics")
    assert exc.value.kind == "upstream"


async def test_fetch_refuses_vevent_root(dns: dict[str, list[str]]) -> None:
    body = "BEGIN:VEVENT\r\nSUMMARY:loose\r\nEND:VEVENT\r\n"
    async with _serve({"/feed.ics": _ics_handler(body)}) as (port, _hits):
        with pytest.raises(CalendarError) as exc:
            await fetch_calendar_feed(f"http://feed.example:{port}/feed.ics")
    assert exc.value.kind == "upstream"


async def test_fetch_refuses_streamed_body_over_five_mib(dns: dict[str, list[str]]) -> None:
    payload = _oversized_ics()

    async def handler(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/calendar"})
        await response.prepare(request)
        for offset in range(0, len(payload), 64 * 1024):
            await response.write(payload[offset : offset + 64 * 1024])
        await response.write_eof()
        return response

    async with _serve({"/feed.ics": handler}) as (port, _hits):
        with pytest.raises(CalendarError) as exc:
            await fetch_calendar_feed(f"http://feed.example:{port}/feed.ics")
    assert exc.value.kind == "upstream"


async def test_fetch_refuses_declared_oversized_content_length(
    dns: dict[str, list[str]],
) -> None:
    async def handler(request: web.Request) -> web.StreamResponse:
        return web.Response(body=_oversized_ics())

    async with _serve({"/feed.ics": handler}) as (port, _hits):
        with pytest.raises(CalendarError) as exc:
            await fetch_calendar_feed(f"http://feed.example:{port}/feed.ics")
    assert exc.value.kind == "upstream"


async def test_fetch_refuses_invalid_compressed_response(dns: dict[str, list[str]]) -> None:
    async def handler(request: web.Request) -> web.StreamResponse:
        return web.Response(body=ICS.encode(), headers={"Content-Encoding": "gzip"})

    async with _serve({"/feed.ics": handler}) as (port, _hits):
        with pytest.raises(CalendarError) as exc:
            await fetch_calendar_feed(f"http://feed.example:{port}/feed.ics")
    assert exc.value.kind == "upstream"


async def test_fetch_reports_timeout(
    dns: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calendar_feeds, "_TOTAL_TIMEOUT_SECONDS", 0.1)
    release = asyncio.Event()

    async def handler(request: web.Request) -> web.StreamResponse:
        await release.wait()
        return web.Response(body=ICS.encode())

    async with _serve({"/feed.ics": handler}) as (port, _hits):
        try:
            with pytest.raises(CalendarError) as exc:
                await fetch_calendar_feed(f"http://feed.example:{port}/feed.ics")
        finally:
            release.set()
    assert exc.value.kind == "timeout"


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
async def test_fetch_decodes_compressed_calendars(dns: dict[str, list[str]], encoding: str) -> None:
    payload = gzip.compress(ICS.encode()) if encoding == "gzip" else zlib.compress(ICS.encode())

    async def handler(request: web.Request) -> web.StreamResponse:
        return web.Response(body=payload, headers={"Content-Encoding": encoding})

    async with _serve({"/feed.ics": handler}) as (port, _hits):
        calendar = await fetch_calendar_feed(f"http://feed.example:{port}/feed.ics")
    event = calendar.walk("VEVENT")[0]
    assert event.decoded("DTSTART").isoformat() == "2026-01-02T09:00:00+00:00"
    assert event.decoded("DTEND").isoformat() == "2026-01-02T09:30:00+00:00"


@pytest.mark.parametrize(
    "payload",
    [
        gzip.compress(_oversized_ics()),
        gzip.compress(ICS.encode())[:-2],
    ],
)
async def test_fetch_rejects_compression_bombs_and_incomplete_streams(
    dns: dict[str, list[str]], payload: bytes
) -> None:
    async def handler(request: web.Request) -> web.StreamResponse:
        return web.Response(body=payload, headers={"Content-Encoding": "gzip"})

    async with _serve({"/feed.ics": handler}) as (port, _hits):
        with pytest.raises(CalendarError) as failure:
            await fetch_calendar_feed(f"http://feed.example:{port}/feed.ics")
    assert failure.value.kind == "upstream"
