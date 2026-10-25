"""Read-only Google Calendar access: OAuth with PKCE, calendar listing, and event fetch.

Events come from ``events.list`` with ``singleEvents=true``, so Google has already expanded
recurrences and each item becomes a non-recurring VEVENT. Timed values are stored as absolute
UTC instants: a fall-back wall-clock time is ambiguous in a TZID, but never in UTC.
"""

import base64
import hashlib
import re
import time
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import quote, urlencode

import httpx
import icalendar

from app.schemas.calendar import CalendarInfo
from app.services.calendar_errors import CalendarError

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
CALENDAR_READ_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
SCOPES = ("openid", "email", CALENDAR_READ_SCOPE)
READABLE_ROLES = frozenset({"owner", "writer", "reader"})
RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded"})
RECONNECT_MESSAGE = "Google Calendar access expired or was revoked; reconnect Google Calendar"
PRODID = "-//Hellweek//Google Calendar adapter//EN"
PAGE_SIZE = 250
EXPIRY_MARGIN_SECONDS = 60
VERIFIER_PATTERN = re.compile(r"[A-Za-z0-9._~-]{43,128}")

JsonObject = dict[str, Any]


def _malformed() -> CalendarError:
    return CalendarError("upstream", "Google returned an unexpected calendar response")


def _code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _expires_after(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return float(value) > time.time() + EXPIRY_MARGIN_SECONDS
    except ValueError:
        return False


def _parse_object(response: httpx.Response) -> JsonObject:
    try:
        data = response.json()
    except ValueError as exc:
        raise _malformed() from exc
    if not isinstance(data, dict):
        raise _malformed()
    return data


def _error_code(response: httpx.Response) -> str:
    """The OAuth ``error`` code from a token response; never the raw body."""
    try:
        data = response.json()
    except ValueError:
        return ""
    error = data.get("error") if isinstance(data, dict) else None
    return error if isinstance(error, str) else ""


def _error_reason(response: httpx.Response) -> str:
    """The Google API ``reason`` from an error response; never the raw body."""
    try:
        data = response.json()
    except ValueError:
        return ""
    error = data.get("error") if isinstance(data, dict) else None
    errors = error.get("errors") if isinstance(error, dict) else None
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        reason = errors[0].get("reason")
        if isinstance(reason, str):
            return reason
    return ""


def _raise_for_api_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    status = response.status_code
    if status == 401:
        raise CalendarError("unauthorized", RECONNECT_MESSAGE)
    if status == 403:
        if _error_reason(response) in RATE_LIMIT_REASONS:
            raise CalendarError("upstream", "Google Calendar rate limit reached; try again later")
        raise CalendarError("forbidden", "Google denied access; reconnect Google Calendar")
    if status == 404:
        raise CalendarError("invalid_request", "Google Calendar was not found")
    raise CalendarError("upstream", f"Google Calendar request failed with HTTP {status}")


def _items(payload: JsonObject) -> list[JsonObject]:
    items = payload.get("items", [])
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise _malformed()
    return items


def _next_page_token(payload: JsonObject, seen: set[str]) -> str | None:
    token = payload.get("nextPageToken")
    if token is None:
        return None
    if not isinstance(token, str) or not token or token in seen:
        raise _malformed()
    seen.add(token)
    return token


def _token_fields(payload: JsonObject) -> tuple[str, int]:
    token = payload.get("access_token")
    expires_in = payload.get("expires_in")
    if (
        not isinstance(token, str)
        or not token
        or not isinstance(expires_in, int)
        or isinstance(expires_in, bool)
        or expires_in <= 0
    ):
        raise CalendarError("upstream", "Google returned an unexpected token response")
    return token, expires_in


def _calendar_info(item: JsonObject) -> CalendarInfo | None:
    if item.get("accessRole") not in READABLE_ROLES:
        return None
    calendar_id = item.get("id")
    if not isinstance(calendar_id, str) or not calendar_id.strip():
        raise _malformed()
    summary = item.get("summary")
    name = summary.strip() if isinstance(summary, str) and summary.strip() else calendar_id
    zone = item.get("timeZone")
    timezone = zone.strip() if isinstance(zone, str) and zone.strip() else None
    return CalendarInfo(
        id=calendar_id, name=name, timezone=timezone, primary=item.get("primary") is True
    )


def _event_moment(raw: object) -> date | datetime:
    if not isinstance(raw, dict):
        raise _malformed()
    day = raw.get("date")
    if isinstance(day, str):
        try:
            return date.fromisoformat(day)
        except ValueError as exc:
            raise _malformed() from exc
    value = raw.get("dateTime")
    if not isinstance(value, str):
        raise _malformed()
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _malformed() from exc
    if moment.tzinfo is None:
        raise _malformed()
    return moment.astimezone(UTC)


def _event_component(item: JsonObject, stamp: datetime) -> icalendar.Event:
    event_id = item.get("id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise _malformed()
    start = _event_moment(item.get("start"))
    end = _event_moment(item.get("end"))
    if isinstance(start, datetime) != isinstance(end, datetime) or end < start:
        raise _malformed()
    event = icalendar.Event()
    event.add("UID", event_id)
    event.add("DTSTAMP", stamp)
    event.add("DTSTART", start)
    event.add("DTEND", end)
    text_fields = (
        ("summary", "SUMMARY"),
        ("location", "LOCATION"),
        ("description", "DESCRIPTION"),
    )
    for field, prop in text_fields:
        value = item.get(field)
        if isinstance(value, str) and value:
            event.add(prop, value)
    return event


def _rfc3339(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


class GoogleCalendarProvider:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> None:
        self._http = http
        self._client_id = client_id.strip()
        self._client_secret = client_secret.strip()
        self._redirect_uri = redirect_uri.strip()

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._client_secret and self._redirect_uri)

    def _require_configured(self) -> None:
        if not self.configured:
            raise CalendarError("not_configured", "Google Calendar is not configured")

    def authorization_url(self, state: str, code_verifier: str) -> str:
        self._require_configured()
        if not state:
            raise CalendarError("invalid_request", "OAuth state must not be empty")
        if VERIFIER_PATTERN.fullmatch(code_verifier) is None:
            raise CalendarError("invalid_request", "PKCE code verifier is malformed")
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "state": state,
                "code_challenge": _code_challenge(code_verifier),
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "consent select_account",
            }
        )
        return f"{AUTHORIZATION_ENDPOINT}?{query}"

    async def exchange_code(self, code: str, code_verifier: str) -> dict[str, str]:
        self._require_configured()
        if not code:
            raise CalendarError("invalid_request", "Authorization code must not be empty")
        if VERIFIER_PATTERN.fullmatch(code_verifier) is None:
            raise CalendarError("invalid_request", "PKCE code verifier is malformed")
        payload = await self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": self._redirect_uri,
            },
            invalid_grant_message="Google sign-in expired or was already used; connect again",
        )
        scope = payload.get("scope")
        if not isinstance(scope, str) or CALENDAR_READ_SCOPE not in scope.split():
            raise CalendarError(
                "forbidden",
                "Google did not grant read-only calendar access; connect again and allow it",
            )
        token, expires_in = _token_fields(payload)
        credentials = {
            "access_token": token,
            "expires_at": str(int(time.time()) + expires_in),
        }
        refresh_token = payload.get("refresh_token")
        if isinstance(refresh_token, str) and refresh_token:
            credentials["refresh_token"] = refresh_token
        credentials["account"] = await self._account_email(token)
        return credentials

    async def list_calendars(
        self, credentials: dict[str, str]
    ) -> tuple[list[CalendarInfo], dict[str, str]]:
        self._require_configured()
        items, current = await self._all_items(
            f"{CALENDAR_API}/users/me/calendarList",
            {"maxResults": str(PAGE_SIZE)},
            credentials,
        )
        calendars = [info for item in items if (info := _calendar_info(item)) is not None]
        return calendars, current

    async def fetch_calendar(
        self,
        credentials: dict[str, str],
        calendar_id: str,
        start: datetime,
        end: datetime,
    ) -> tuple[icalendar.Calendar, dict[str, str]]:
        self._require_configured()
        if not calendar_id.strip():
            raise CalendarError("invalid_request", "Calendar id must not be blank")
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise CalendarError(
                "invalid_request", "Choose an aware time window that ends after it starts"
            )
        url = f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events"
        items, current = await self._all_items(
            url,
            {
                "timeMin": _rfc3339(start),
                "timeMax": _rfc3339(end),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": str(PAGE_SIZE),
            },
            credentials,
        )
        calendar = icalendar.Calendar()
        calendar.add("PRODID", PRODID)
        calendar.add("VERSION", "2.0")
        stamp = datetime.now(UTC)
        for item in items:
            if item.get("status") == "cancelled":
                continue
            calendar.add_component(_event_component(item, stamp))
        return calendar, current

    async def _all_items(
        self, url: str, params: dict[str, str], credentials: dict[str, str]
    ) -> tuple[list[JsonObject], dict[str, str]]:
        current = dict(credentials)
        items: list[JsonObject] = []
        seen: set[str] = set()
        page_token: str | None = None
        while True:
            page_params = dict(params)
            if page_token is not None:
                page_params["pageToken"] = page_token
            payload, current = await self._api_get(url, page_params, current)
            items.extend(_items(payload))
            page_token = _next_page_token(payload, seen)
            if page_token is None:
                return items, current

    async def _api_get(
        self, url: str, params: dict[str, str], credentials: dict[str, str]
    ) -> tuple[JsonObject, dict[str, str]]:
        token, current = await self._fresh_access_token(credentials, force=False)
        response = await self._send_get(url, params, token)
        if response.status_code == 401:
            token, current = await self._fresh_access_token(current, force=True)
            response = await self._send_get(url, params, token)
        _raise_for_api_status(response)
        return _parse_object(response), current

    async def _send_get(
        self, url: str, params: dict[str, str] | None, access_token: str
    ) -> httpx.Response:
        try:
            return await self._http.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise CalendarError("timeout", "Google Calendar request timed out") from exc
        except httpx.HTTPError as exc:
            raise CalendarError("upstream", "Google Calendar request failed") from exc

    async def _fresh_access_token(
        self, credentials: dict[str, str], *, force: bool
    ) -> tuple[str, dict[str, str]]:
        token = credentials.get("access_token")
        if not force and token and _expires_after(credentials.get("expires_at")):
            return token, dict(credentials)
        refreshed = await self._refresh(credentials)
        return refreshed["access_token"], refreshed

    async def _refresh(self, credentials: dict[str, str]) -> dict[str, str]:
        refresh_token = credentials.get("refresh_token")
        if not refresh_token:
            raise CalendarError("unauthorized", RECONNECT_MESSAGE)
        payload = await self._post_token(
            {"grant_type": "refresh_token", "refresh_token": refresh_token},
            invalid_grant_message=RECONNECT_MESSAGE,
        )
        token, expires_in = _token_fields(payload)
        updated = dict(credentials)
        updated["access_token"] = token
        updated["expires_at"] = str(int(time.time()) + expires_in)
        rotated = payload.get("refresh_token")
        if isinstance(rotated, str) and rotated:
            updated["refresh_token"] = rotated
        return updated

    async def _post_token(self, grant: dict[str, str], *, invalid_grant_message: str) -> JsonObject:
        form = {**grant, "client_id": self._client_id, "client_secret": self._client_secret}
        try:
            response = await self._http.post(
                TOKEN_ENDPOINT, data=form, headers={"Accept": "application/json"}
            )
        except httpx.TimeoutException as exc:
            raise CalendarError("timeout", "Google token request timed out") from exc
        except httpx.HTTPError as exc:
            raise CalendarError("upstream", "Google token request failed") from exc
        if response.is_success:
            return _parse_object(response)
        error = _error_code(response)
        if error == "invalid_grant" or response.status_code == 401:
            raise CalendarError("unauthorized", invalid_grant_message)
        if error == "invalid_client":
            raise CalendarError("upstream", "Google rejected the OAuth client configuration")
        raise CalendarError(
            "upstream", f"Google token request failed with HTTP {response.status_code}"
        )

    async def _account_email(self, access_token: str) -> str:
        response = await self._send_get(USERINFO_ENDPOINT, None, access_token)
        _raise_for_api_status(response)
        email = _parse_object(response).get("email")
        if not isinstance(email, str) or not email.strip():
            raise CalendarError("upstream", "Google did not return an account email")
        return email.strip()
