"""Public ICS feed import and Google Calendar link recognition.

Google web and embed links name a calendar that the Google adapter reads through OAuth, so they
are identified here instead of being fetched. Every other URL is fetched as an ICS feed over
aiohttp: each connection is pinned to globally routable addresses returned by _PublicResolver,
redirects are revalidated hop by hop, and the body is bounded before it is parsed.
"""

import asyncio
import base64
import ipaddress
import re
import socket
import zlib
from collections.abc import Awaitable, Callable
from ipaddress import IPv4Address, IPv6Address, IPv6Network
from typing import Final
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

import aiohttp
import icalendar
from aiohttp.abc import AbstractResolver, ResolveResult

from app.services.calendar_errors import CalendarError

__all__ = ["fetch_calendar_feed", "google_calendar_id"]

_TOTAL_TIMEOUT_SECONDS: Final = 30
_MAX_BYTES: Final = 5 * 1024 * 1024
_CHUNK_BYTES: Final = 64 * 1024
_MAX_REDIRECTS: Final = 5
_MAX_URL_LENGTH: Final = 8192
_REDIRECT_STATUSES: Final = frozenset({301, 302, 303, 307, 308})
_REQUEST_HEADERS: Final = {
    "Accept": "text/calendar, text/plain;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "User-Agent": "Hellweek-Calendar-Import",
}
_SCHEMES: Final = frozenset({"http", "https"})
_GOOGLE_SCHEMES: Final = frozenset({"http", "https", "webcal"})
_GOOGLE_HOST: Final = "calendar.google.com"
_GOOGLE_LEGACY_HOST: Final = "www.google.com"
_GOOGLE_ICAL_PREFIX: Final = "/calendar/ical/"
_GOOGLE_EVENT_SEGMENTS: Final = frozenset({"event", "eventedit"})
_GOOGLE_CALENDAR_PARAMS: Final = frozenset({"src", "cid"})

_UNSAFE: Final = re.compile(r"[\x00-\x20\x7f\\]")
_HOST_NAME: Final = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+"
)
_NUMERIC_LABEL: Final = re.compile(r"0x[0-9a-f]*|[0-9]+")
_CALENDAR_ID: Final = re.compile(r"[A-Za-z0-9._+#-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_BASE64URL: Final = re.compile(r"[A-Za-z0-9_-]+")
_NAT64: Final = IPv6Network("64:ff9b::/96")
_TEREDO: Final = IPv6Network("2001::/32")

_BAD_URL: Final = "Calendar URL must be an absolute http, https, or webcal link to a public host"
_CREDENTIALS: Final = "Calendar URL must not contain a username or password"
_PRIVATE_HOST: Final = "Calendar URL must point to a public internet address"
_GOOGLE_WEB: Final = (
    "Google Calendar links are imported through the Google Calendar connection, not as ICS feeds"
)
_GOOGLE_EVENT: Final = (
    "Google Calendar event links are not calendar feeds; paste the calendar's link instead"
)
_GOOGLE_MALFORMED: Final = "Google Calendar link does not name a valid calendar"
_GOOGLE_AMBIGUOUS: Final = "Google Calendar link names more than one calendar"
_UNSAFE_REDIRECT: Final = "Calendar feed redirected to an unsafe location"
_DOWNGRADE: Final = "Calendar feed redirected from HTTPS to HTTP"
_REDIRECT_LOOP: Final = "Calendar feed redirected in a loop"
_TOO_MANY_REDIRECTS: Final = "Calendar feed redirected too many times"
_NO_LOCATION: Final = "Calendar feed sent a redirect without a location"
_NO_PUBLIC_ADDRESS: Final = "Calendar host did not resolve to a public internet address"
_UNREACHABLE: Final = "Calendar feed could not be reached"
_TIMEOUT: Final = "Calendar feed did not respond in time"
_UNAUTHORIZED: Final = (
    "Calendar feed requires sign-in; connect Google Calendar or use an ICS link that works "
    "without signing in"
)
_FORBIDDEN: Final = (
    "Calendar feed denied access; it may be private. Connect Google Calendar or use a valid "
    "ICS link"
)
_NOT_FOUND: Final = "Calendar feed was not found at that URL"
_ENCODED: Final = "Calendar feed uses an unsupported content encoding"
_TOO_LARGE: Final = "Calendar feed is larger than 5 MiB"
_MALFORMED: Final = "Calendar feed is not a valid ICS calendar"

_Lookup = Callable[[str, int, int], Awaitable[list[str]]]


def google_calendar_id(url: str) -> str | None:
    """Return the Google calendar id named by a Google web/embed link.

    Returns None for every URL that is not a Google web link: Google ICS URLs and all other hosts
    are left for fetch_calendar_feed. Malformed Google links, Google event-edit links, and links
    naming more than one calendar raise CalendarError("invalid_request").
    """
    text = url.strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    host = parts.hostname
    path = parts.path
    is_google = host == _GOOGLE_HOST or (
        host == _GOOGLE_LEGACY_HOST and (path == "/calendar" or path.startswith("/calendar/"))
    )
    if not is_google:
        return None

    try:
        port = parts.port
    except ValueError:
        raise CalendarError("invalid_request", _GOOGLE_MALFORMED) from None
    scheme = parts.scheme.lower()
    if (
        _UNSAFE.search(text)
        or parts.fragment
        or "@" in parts.netloc
        or port is not None
        or scheme not in _GOOGLE_SCHEMES
    ):
        raise CalendarError("invalid_request", _GOOGLE_MALFORMED)
    if path.lower().startswith(_GOOGLE_ICAL_PREFIX):
        return None
    if scheme != "https":
        raise CalendarError("invalid_request", _GOOGLE_MALFORMED)

    query = parse_qsl(parts.query, keep_blank_values=True)
    segments = {segment.lower() for segment in path.split("/")}
    if segments & _GOOGLE_EVENT_SEGMENTS or any(key == "eid" for key, _ in query):
        raise CalendarError("invalid_request", _GOOGLE_EVENT)
    pairs = [(key, value) for key, value in query if key in _GOOGLE_CALENDAR_PARAMS]
    if not pairs:
        raise CalendarError("invalid_request", _GOOGLE_MALFORMED)
    ids = {_google_calendar_id(key, value) for key, value in pairs}
    if len(ids) > 1:
        raise CalendarError("invalid_request", _GOOGLE_AMBIGUOUS)
    return ids.pop()


def _google_calendar_id(key: str, value: str) -> str:
    candidate = value if key == "src" or "@" in value else _decode_cid(value)
    if len(candidate) > 254 or not _CALENDAR_ID.fullmatch(candidate):
        raise CalendarError("invalid_request", _GOOGLE_MALFORMED)
    return candidate


def _decode_cid(value: str) -> str:
    """Decode a URL-safe base64 Google cid (padding optional) into the calendar id."""
    stripped = value.rstrip("=")
    if not _BASE64URL.fullmatch(stripped) or len(stripped) % 4 == 1:
        raise CalendarError("invalid_request", _GOOGLE_MALFORMED)
    padded = stripped + "=" * (-len(stripped) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("ascii")
    except ValueError:
        raise CalendarError("invalid_request", _GOOGLE_MALFORMED) from None


def _is_global_ip(ip: IPv4Address | IPv6Address) -> bool:
    """True only for globally routable unicast addresses, unwrapping embedded IPv4 forms."""
    if isinstance(ip, IPv6Address):
        if ip in _TEREDO:
            return False
        if ip.ipv4_mapped is not None:
            return _is_global_ip(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return _is_global_ip(ip.sixtofour)
        if ip in _NAT64:
            return _is_global_ip(IPv4Address(ip.packed[-4:]))
    return ip.is_global and not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _public_host(host: str | None) -> str:
    """Return the netloc form of a hostname or IP literal, or reject it."""
    if not host:
        raise CalendarError("invalid_request", _BAD_URL)
    try:
        literal: IPv4Address | IPv6Address | None = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not _is_global_ip(literal):
            raise CalendarError("invalid_request", _PRIVATE_HOST)
        return f"[{host}]" if literal.version == 6 else host
    if (
        len(host) > 253
        or not _HOST_NAME.fullmatch(host)
        or host == "localhost"
        or host.endswith(".localhost")
    ):
        raise CalendarError("invalid_request", _BAD_URL)
    # Alternate numeric IPv4 spellings (127.1, 0177.0.0.1, 0x7f000001) end in a numeric label;
    # no public DNS name does, so they are refused rather than interpreted.
    if _NUMERIC_LABEL.fullmatch(host.rsplit(".", 1)[-1]):
        raise CalendarError("invalid_request", _BAD_URL)
    return host


def _public_url(raw: str) -> str:
    """Normalize a user-supplied feed URL to an absolute http(s) URL on a public host."""
    text = raw.strip()
    if (
        not text
        or len(text) > _MAX_URL_LENGTH
        or not text.isascii()
        or "#" in text
        or _UNSAFE.search(text)
    ):
        raise CalendarError("invalid_request", _BAD_URL)
    try:
        parts = urlsplit(text)
    except ValueError:
        raise CalendarError("invalid_request", _BAD_URL) from None
    if "@" in parts.netloc:
        raise CalendarError("invalid_request", _CREDENTIALS)
    try:
        port = parts.port
    except ValueError:
        raise CalendarError("invalid_request", _BAD_URL) from None
    scheme = parts.scheme.lower()
    if scheme == "webcal":
        scheme = "https"
    if scheme not in _SCHEMES or port == 0:
        raise CalendarError("invalid_request", _BAD_URL)
    host = _public_host(parts.hostname)
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def _redirect_target(current: str, location: str) -> str:
    """Validate one redirect hop: public target, no HTTPS-to-HTTP downgrade."""
    try:
        target = _public_url(urljoin(current, location))
    except CalendarError:
        raise CalendarError("upstream", _UNSAFE_REDIRECT) from None
    if urlsplit(current).scheme == "https" and urlsplit(target).scheme == "http":
        raise CalendarError("upstream", _DOWNGRADE)
    return target


async def _system_addresses(host: str, port: int, family: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, family=family, type=socket.SOCK_STREAM
    )
    return [str(info[4][0]) for info in infos]


class _PublicResolver(AbstractResolver):
    """Resolve only to globally routable addresses; aiohttp connects to exactly these."""

    def __init__(self, lookup: _Lookup | None = None) -> None:
        self._lookup: _Lookup = lookup if lookup is not None else _system_addresses

    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_INET
    ) -> list[ResolveResult]:
        results: list[ResolveResult] = []
        seen: set[str] = set()
        for raw in await self._lookup(host, port, family):
            try:
                ip = ipaddress.ip_address(raw)
            except ValueError:
                continue
            address = str(ip)
            if not _is_global_ip(ip) or address in seen:
                continue
            seen.add(address)
            results.append(
                {
                    "hostname": host,
                    "host": address,
                    "port": port,
                    "family": socket.AF_INET6 if ip.version == 6 else socket.AF_INET,
                    "proto": socket.IPPROTO_TCP,
                    "flags": socket.AI_NUMERICHOST,
                }
            )
        if not results:
            raise CalendarError("upstream", _NO_PUBLIC_ADDRESS)
        return results

    async def close(self) -> None:
        return None


def _status_error(status: int) -> CalendarError:
    if status == 401:
        return CalendarError("unauthorized", _UNAUTHORIZED)
    if status == 403:
        return CalendarError("forbidden", _FORBIDDEN)
    if status == 404:
        return CalendarError("invalid_request", _NOT_FOUND)
    return CalendarError("upstream", f"Calendar feed server returned HTTP {status}")


async def _body(response: aiohttp.ClientResponse) -> bytes:
    if response.status != 200:
        raise _status_error(response.status)
    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    if encoding not in ("identity", "gzip", "x-gzip", "deflate"):
        raise CalendarError("upstream", _ENCODED)
    decoder = (
        zlib.decompressobj(
            16 + zlib.MAX_WBITS if encoding in ("gzip", "x-gzip") else zlib.MAX_WBITS
        )
        if encoding != "identity"
        else None
    )
    declared = response.content_length
    if declared is not None and declared > _MAX_BYTES:
        raise CalendarError("upstream", _TOO_LARGE)
    buffer = bytearray()
    transferred = 0
    async for chunk in response.content.iter_chunked(_CHUNK_BYTES):
        transferred += len(chunk)
        if transferred > _MAX_BYTES:
            raise CalendarError("upstream", _TOO_LARGE)
        if decoder is not None:
            try:
                chunk = decoder.decompress(chunk, _MAX_BYTES - len(buffer) + 1)
            except zlib.error:
                raise CalendarError("upstream", _MALFORMED) from None
            if decoder.unused_data:
                raise CalendarError("upstream", _MALFORMED)
        if len(buffer) + len(chunk) > _MAX_BYTES:
            raise CalendarError("upstream", _TOO_LARGE)
        buffer.extend(chunk)
    if decoder is not None and not decoder.eof:
        raise CalendarError("upstream", _MALFORMED)
    return bytes(buffer)


async def _download(start: str) -> bytes:
    connector = aiohttp.TCPConnector(
        resolver=_PublicResolver(), use_dns_cache=False, force_close=True
    )
    async with aiohttp.ClientSession(
        connector=connector,
        headers=_REQUEST_HEADERS,
        cookie_jar=aiohttp.DummyCookieJar(),
        trust_env=False,
        auto_decompress=False,
        timeout=aiohttp.ClientTimeout(total=_TOTAL_TIMEOUT_SECONDS),
    ) as session:
        current = start
        seen = {start}
        redirects = 0
        while True:
            async with session.get(current, allow_redirects=False) as response:
                if response.status not in _REDIRECT_STATUSES:
                    return await _body(response)
                location = response.headers.get("Location")
                if location is None:
                    raise CalendarError("upstream", _NO_LOCATION)
                if redirects == _MAX_REDIRECTS:
                    raise CalendarError("upstream", _TOO_MANY_REDIRECTS)
                redirects += 1
                target = _redirect_target(current, location)
                if target in seen:
                    raise CalendarError("upstream", _REDIRECT_LOOP)
                seen.add(target)
                current = target


def _parse_calendar(body: bytes) -> icalendar.Calendar:
    try:
        text = body.decode("utf-8").removeprefix("\ufeff")
    except UnicodeDecodeError:
        raise CalendarError("upstream", _MALFORMED) from None
    try:
        parsed = icalendar.Calendar.from_ical(text)
    except (ValueError, TypeError, KeyError, IndexError):
        raise CalendarError("upstream", _MALFORMED) from None
    if parsed.name != "VCALENDAR":
        raise CalendarError("upstream", _MALFORMED)
    return parsed


async def fetch_calendar_feed(url: str) -> icalendar.Calendar:
    """Fetch a public ICS feed and return its parsed VCALENDAR.

    webcal:// is treated as https://. Google web links are rejected here; use google_calendar_id
    to route them through the Google adapter.
    """
    if google_calendar_id(url) is not None:
        raise CalendarError("invalid_request", _GOOGLE_WEB)
    start = _public_url(url)
    try:
        async with asyncio.timeout(_TOTAL_TIMEOUT_SECONDS):
            body = await _download(start)
    except CalendarError:
        raise
    except TimeoutError:
        raise CalendarError("timeout", _TIMEOUT) from None
    except (aiohttp.ClientError, OSError):
        raise CalendarError("upstream", _UNREACHABLE) from None
    return _parse_calendar(body)
