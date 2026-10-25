"""Read-only Apple iCloud CalDAV adapter (RFC 4791) for calendar discovery and VEVENT queries.

Discovery runs current-user-principal -> calendar-home-set -> child collections. Every href is
validated against trusted iCloud hostnames before an authenticated request is sent. Event data is
returned as full calendar-data; recurrence expansion is left to the existing parser.
"""

import base64
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
from xml.etree.ElementTree import Element
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import icalendar
from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring

from app.schemas.calendar import CalendarInfo
from app.services.calendar_errors import CalendarError, CalendarErrorKind

BASE_URL: Final = "https://caldav.icloud.com/"
HOME_URL_KEY: Final = "calendar_home_url"

_MAX_REDIRECTS: Final = 5
_REDIRECT_STATUSES: Final = frozenset({301, 302, 303, 307, 308})
_TRUSTED_HOST: Final = re.compile(r"(?:p[0-9]{1,3}-)?caldav\.icloud\.com")
_UNSAFE: Final = re.compile(r"[\x00-\x20\x7f\\?#]")
_UNSAFE_DECODED_PATH: Final = re.compile(r"[\x00-\x1f\x7f\\]")
_STATUS_LINE: Final = re.compile(r"HTTP/1\.[01] ([0-9]{3})(?: .*)?")
_DAV_NS: Final = "DAV:"
_CALDAV_NS: Final = "urn:ietf:params:xml:ns:caldav"
_XML_HEADER: Final = '<?xml version="1.0" encoding="utf-8"?>'

_PRINCIPAL_BODY: Final = (
    _XML_HEADER
    + '<D:propfind xmlns:D="DAV:"><D:prop><D:current-user-principal/></D:prop></D:propfind>'
)
_HOME_BODY: Final = (
    _XML_HEADER
    + '<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
    + "<D:prop><C:calendar-home-set/></D:prop></D:propfind>"
)
_CALENDARS_BODY: Final = (
    _XML_HEADER
    + '<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav"><D:prop>'
    + "<D:resourcetype/><D:displayname/>"
    + "<C:supported-calendar-component-set/><C:calendar-timezone/>"
    + "</D:prop></D:propfind>"
)

_MALFORMED: Final = "Apple iCloud returned a malformed CalDAV response"
_INCOMPLETE: Final = "Apple iCloud returned an incomplete calendar response"
_NO_PRINCIPAL: Final = "Apple iCloud did not return a current user principal"
_NO_HOME: Final = "Apple iCloud did not return a calendar home"
_UNAUTHORIZED: Final = "Apple rejected the iCloud Apple ID or app-specific password"
_FORBIDDEN: Final = "Apple iCloud denied calendar access for this account"
_LIMITED: Final = "Apple iCloud limited this calendar query, so the result would be incomplete"
_TIMEOUT: Final = "Apple iCloud did not respond in time"
_UNREACHABLE: Final = "Apple iCloud could not be reached"
_REDIRECTS: Final = "Apple iCloud redirected calendar requests too many times"
_UNTRUSTED: Final = "Calendar location is not a trusted Apple iCloud CalDAV URL"
_NOT_CONFIGURED: Final = "Apple calendar credentials are incomplete"
_BAD_WINDOW: Final = "Calendar window needs timezone-aware values with start before end"
_NOT_A_CALENDAR: Final = "Calendar id must name a calendar in this iCloud account"


def _dav(name: str) -> str:
    return f"{{{_DAV_NS}}}{name}"


def _cal(name: str) -> str:
    return f"{{{_CALDAV_NS}}}{name}"


@dataclass(frozen=True, slots=True)
class _Entry:
    """One DAV:response: 200-status props, names of non-200 props, and response-level status."""

    href: str
    status: int | None
    found: dict[str, Element]
    failed: frozenset[str]


class AppleCalendarProvider:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def list_calendars(
        self, credentials: dict[str, str]
    ) -> tuple[list[CalendarInfo], dict[str, str]]:
        auth = _basic_auth(credentials)
        home = await self._discover_home(auth)
        response, base = await self._send(
            "PROPFIND", home, auth=auth, depth="1", body=_CALENDARS_BODY
        )
        home_path = urlsplit(base).path
        calendars: list[CalendarInfo] = []
        seen: set[str] = set()
        for entry in _entries(_multistatus(response)):
            if not _succeeded(entry):
                continue
            child_path = urlsplit(_collection_url(entry.href, base=base)).path
            if child_path == home_path:
                continue
            calendar_path = _collection_within(child_path, home_path, "upstream")
            if calendar_path is None or calendar_path in seen or not _is_event_calendar(entry):
                continue
            seen.add(calendar_path)
            calendars.append(
                CalendarInfo(
                    id=calendar_path,
                    name=_text(entry.found.get(_dav("displayname")))
                    or calendar_path.rstrip("/").rsplit("/", 1)[-1],
                    timezone=_timezone(entry.found.get(_cal("calendar-timezone"))),
                )
            )
        return calendars, {**credentials, HOME_URL_KEY: base}

    async def fetch_calendar(
        self,
        credentials: dict[str, str],
        calendar_id: str,
        start: datetime,
        end: datetime,
    ) -> tuple[icalendar.Calendar, dict[str, str]]:
        auth = _basic_auth(credentials)
        start_stamp, end_stamp = _window(start, end)
        calendar_path = _calendar_path(calendar_id)
        home = _cached_home(credentials) or await self._discover_home(auth)
        home_path = urlsplit(home).path
        calendar_url = _collection_url(calendar_path, base=home, kind="invalid_request")
        if _collection_within(urlsplit(calendar_url).path, home_path, "invalid_request") is None:
            raise CalendarError("invalid_request", _NOT_A_CALENDAR)

        response, final = await self._send(
            "REPORT",
            calendar_url,
            auth=auth,
            depth="1",
            body=_report_body(start_stamp, end_stamp),
        )
        calendar = _empty_calendar()
        timezones: set[str] = set()
        for entry in _entries(_multistatus(response)):
            if not _succeeded(entry):
                raise CalendarError("upstream", _INCOMPLETE)
            resource = _trusted_url(entry.href, base=final)
            if not urlsplit(resource).path.startswith(calendar_path):
                raise CalendarError("upstream", _UNTRUSTED)
            data = entry.found.get(_cal("calendar-data"))
            if data is None or _cal("calendar-data") in entry.failed:
                raise CalendarError("upstream", _INCOMPLETE)
            _merge(calendar, _parse_resource(data.text or ""), timezones)
        return calendar, {**credentials, HOME_URL_KEY: home}

    async def _discover_home(self, auth: str) -> str:
        response, base = await self._send(
            "PROPFIND", BASE_URL, auth=auth, depth="0", body=_PRINCIPAL_BODY
        )
        principal = _entry_at(_multistatus(response), base).found.get(
            _dav("current-user-principal")
        )
        if principal is None:
            raise CalendarError("upstream", _NO_PRINCIPAL)
        if principal.find(_dav("unauthenticated")) is not None:
            raise CalendarError("unauthorized", _UNAUTHORIZED)
        principal_hrefs = _hrefs(principal)
        if len(principal_hrefs) != 1:
            raise CalendarError("upstream", _MALFORMED)
        principal_url = _collection_url(principal_hrefs[0], base=base)

        response, base = await self._send(
            "PROPFIND", principal_url, auth=auth, depth="0", body=_HOME_BODY
        )
        home_set = _entry_at(_multistatus(response), base).found.get(_cal("calendar-home-set"))
        if home_set is None:
            raise CalendarError("upstream", _NO_HOME)
        homes = [_collection_url(href, base=base) for href in _hrefs(home_set)]
        if not homes:
            raise CalendarError("upstream", _NO_HOME)
        return homes[0]

    async def _send(
        self, method: str, url: str, *, auth: str, depth: str, body: str
    ) -> tuple[httpx.Response, str]:
        """Send one DAV request, following only trusted same-provider redirects manually.

        Returns the final response and the URL it was served from, used to resolve relative hrefs.
        """
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            try:
                response = await self._http.request(
                    method,
                    current,
                    headers={
                        "Authorization": auth,
                        "Depth": depth,
                        "Content-Type": "application/xml; charset=utf-8",
                    },
                    content=body.encode("utf-8"),
                    follow_redirects=False,
                )
            except httpx.TimeoutException as exc:
                raise CalendarError("timeout", _TIMEOUT) from exc
            except httpx.HTTPError as exc:
                raise CalendarError("upstream", _UNREACHABLE) from exc
            if response.status_code not in _REDIRECT_STATUSES:
                return response, current
            location = response.headers.get("location")
            if not location:
                raise CalendarError("upstream", _MALFORMED)
            current = _trusted_url(location, base=current)
        raise CalendarError("upstream", _REDIRECTS)


def _basic_auth(credentials: dict[str, str]) -> str:
    username = credentials.get("username", "")
    password = credentials.get("app_password", "")
    if not username.strip() or not password or ":" in username or not username.isprintable():
        raise CalendarError("not_configured", _NOT_CONFIGURED)
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def _cached_home(credentials: dict[str, str]) -> str | None:
    raw = credentials.get(HOME_URL_KEY)
    if not raw:
        return None
    try:
        return _collection_url(raw, base=BASE_URL)
    except CalendarError:
        return None


def _trusted_url(candidate: str, *, base: str, kind: CalendarErrorKind = "upstream") -> str:
    """Resolve an href/redirect against base; accept only HTTPS Apple iCloud CalDAV URLs."""
    if not candidate or _UNSAFE.search(candidate):
        raise CalendarError(kind, _UNTRUSTED)
    try:
        parts = urlsplit(urljoin(base, candidate))
        port = parts.port
    except ValueError as exc:
        raise CalendarError(kind, _UNTRUSTED) from exc
    host = parts.hostname
    if (
        parts.scheme != "https"
        or host is None
        or not _TRUSTED_HOST.fullmatch(host)
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or parts.query
        or parts.fragment
    ):
        raise CalendarError(kind, _UNTRUSTED)
    _safe_path(parts.path, kind)
    return urlunsplit(("https", host, quote(parts.path, safe="/%:@!$&'()*+,;=-._~"), "", ""))


def _collection_url(candidate: str, *, base: str, kind: CalendarErrorKind = "upstream") -> str:
    url = _trusted_url(candidate, base=base, kind=kind)
    return url if url.endswith("/") else f"{url}/"


def _safe_path(path: str, kind: CalendarErrorKind) -> None:
    try:
        decoded = unquote(path, errors="strict")
    except UnicodeDecodeError as exc:
        raise CalendarError(kind, _UNTRUSTED) from exc
    if (
        not path.startswith("/")
        or "%2f" in path.lower()
        or "%5c" in path.lower()
        or _UNSAFE_DECODED_PATH.search(decoded)
        or re.search(r"%(?![0-9a-fA-F]{2})", path)
        or any(segment in (".", "..") for segment in decoded.split("/"))
    ):
        raise CalendarError(kind, _UNTRUSTED)


def _calendar_path(calendar_id: str) -> str:
    """Validate a caller-supplied calendar id (an absolute collection path, host-independent)."""
    if (
        not calendar_id.startswith("/")
        or calendar_id.startswith("//")
        or _UNSAFE.search(calendar_id)
    ):
        raise CalendarError("invalid_request", _NOT_A_CALENDAR)
    path = calendar_id if calendar_id.endswith("/") else f"{calendar_id}/"
    _safe_path(path, "invalid_request")
    return quote(path, safe="/%:@!$&'()*+,;=-._~")


def _collection_within(path: str, home_path: str, kind: CalendarErrorKind) -> str | None:
    """Return path if it is a direct child collection of home; None if nested deeper."""
    if not path.startswith(home_path) or path == home_path:
        raise CalendarError(kind, _UNTRUSTED)
    rest = path[len(home_path) :]
    if rest.count("/") != 1 or not rest.endswith("/"):
        return None
    return path


def _window(start: datetime, end: datetime) -> tuple[str, str]:
    if start.utcoffset() is None or end.utcoffset() is None or start >= end:
        raise CalendarError("invalid_request", _BAD_WINDOW)
    return _stamp(start), _stamp(end)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _report_body(start: str, end: str) -> str:
    # Only fixed XML and digits from _stamp are interpolated; no provider or user text.
    return (
        _XML_HEADER
        + '<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
        + "<D:prop><C:calendar-data/></D:prop>"
        + '<C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT">'
        + f'<C:time-range start="{start}" end="{end}"/>'
        + "</C:comp-filter></C:comp-filter></C:filter>"
        + "</C:calendar-query>"
    )


def _multistatus(response: httpx.Response) -> Element:
    code = response.status_code
    if code == 401:
        raise CalendarError("unauthorized", _UNAUTHORIZED)
    if code == 403:
        if b"number-of-matches-within-limits" in response.content:
            raise CalendarError("upstream", _LIMITED)
        raise CalendarError("forbidden", _FORBIDDEN)
    if code != 207:
        raise CalendarError("upstream", f"Apple iCloud returned HTTP {code}")
    try:
        root = fromstring(response.content)
    except (ParseError, DefusedXmlException) as exc:
        raise CalendarError("upstream", _MALFORMED) from exc
    if root.tag != _dav("multistatus"):
        raise CalendarError("upstream", _MALFORMED)
    return root


def _text(element: Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def _hrefs(prop: Element) -> list[str]:
    return [text for child in prop.findall(_dav("href")) if (text := _text(child))]


def _status_code(element: Element | None) -> int:
    match = _STATUS_LINE.fullmatch(_text(element))
    if match is None:
        raise CalendarError("upstream", _MALFORMED)
    return int(match.group(1))


def _entries(root: Element) -> list[_Entry]:
    entries: list[_Entry] = []
    for response in root.findall(_dav("response")):
        href = _text(response.find(_dav("href")))
        if not href:
            raise CalendarError("upstream", _MALFORMED)
        top_status = response.find(_dav("status"))
        status = _status_code(top_status) if top_status is not None else None
        found: dict[str, Element] = {}
        failed: set[str] = set()
        for propstat in response.findall(_dav("propstat")):
            code = _status_code(propstat.find(_dav("status")))
            prop = propstat.find(_dav("prop"))
            if prop is None:
                raise CalendarError("upstream", _MALFORMED)
            for child in prop:
                if code == 200:
                    found[child.tag] = child
                else:
                    failed.add(child.tag)
        entries.append(_Entry(href, status, found, frozenset(failed)))
    return entries


def _succeeded(entry: _Entry) -> bool:
    return entry.status is None or 200 <= entry.status < 300


def _entry_at(root: Element, requested: str) -> _Entry:
    wanted = urlsplit(requested).path.rstrip("/")
    for entry in _entries(root):
        if urlsplit(urljoin(requested, entry.href)).path.rstrip("/") == wanted:
            if not _succeeded(entry):
                raise CalendarError("upstream", _MALFORMED)
            return entry
    raise CalendarError("upstream", _MALFORMED)


def _is_event_calendar(entry: _Entry) -> bool:
    resource_type = entry.found.get(_dav("resourcetype"))
    if resource_type is None or resource_type.find(_cal("calendar")) is None:
        return False
    if _cal("supported-calendar-component-set") in entry.failed:
        return False
    components = entry.found.get(_cal("supported-calendar-component-set"))
    if components is None:
        # RFC 4791 section 5.2.3: an absent component set means every component is supported.
        return True
    return any(comp.get("name") == "VEVENT" for comp in components.findall(_cal("comp")))


def _timezone(element: Element | None) -> str | None:
    text = _text(element)
    if not text:
        return None
    try:
        parsed = icalendar.Calendar.from_ical(text)
    except ValueError:
        return None
    for block in parsed.walk("VTIMEZONE"):
        tzid = str(block.get("TZID", ""))
        try:
            ZoneInfo(tzid)
        except (ZoneInfoNotFoundError, ValueError):
            return None
        return tzid
    return None


def _parse_resource(text: str) -> icalendar.Calendar:
    try:
        parsed = icalendar.Calendar.from_ical(text)
    except ValueError as exc:
        raise CalendarError("upstream", _MALFORMED) from exc
    if parsed.name != "VCALENDAR":
        raise CalendarError("upstream", _MALFORMED)
    return parsed


def _empty_calendar() -> icalendar.Calendar:
    calendar = icalendar.Calendar()
    calendar.add("prodid", "-//Hellweek//Apple iCloud CalDAV//EN")
    calendar.add("version", "2.0")
    return calendar


def _merge(target: icalendar.Calendar, resource: icalendar.Calendar, timezones: set[str]) -> None:
    """Keep every VEVENT (including RECURRENCE-ID overrides) and each VTIMEZONE once by TZID."""
    for component in resource.subcomponents:
        if component.name == "VTIMEZONE":
            tzid = str(component.get("TZID", ""))
            if tzid and tzid in timezones:
                continue
            timezones.add(tzid)
            target.add_component(component)
        elif component.name == "VEVENT":
            target.add_component(component)
