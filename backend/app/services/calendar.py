"""Browser-owned calendar credentials and the shared recurrence parser pipeline."""

import asyncio
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from datetime import time as midnight
from typing import cast
from urllib.parse import quote
from weakref import WeakValueDictionary
from zoneinfo import ZoneInfo

import httpx
import icalendar
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.models.calendar import CalendarBrowserSession, CalendarConnection, CalendarOAuthState
from app.repositories.calendar import CalendarRepository
from app.schemas.calendar import (
    AppleConnectRequest,
    CalendarConnectionInfo,
    CalendarInfo,
    CalendarParseRequest,
    CalendarProvider,
    CalendarSessionResponse,
    CalendarSource,
    CalendarUrlImportRequest,
    CalendarWindow,
    ParsedCalendarEvent,
    ParsedCalendarResponse,
)
from app.services.apple_calendar import AppleCalendarProvider
from app.services.calendar_errors import CalendarError
from app.services.calendar_feeds import fetch_calendar_feed, google_calendar_id
from app.services.google_calendar import GoogleCalendarProvider
from hellweek.parse import expand_events

SESSION_SECONDS = 30 * 24 * 60 * 60


class CalendarService:
    def __init__(
        self, settings: Settings, repository: CalendarRepository, http: httpx.AsyncClient
    ) -> None:
        self.repository = repository
        self.frontend_url = settings.CALENDAR_FRONTEND_URL.rstrip("/")
        self.secure_cookie = settings.ENVIRONMENT != "development"
        self.cookie_name = "__Host-calendar_session" if self.secure_cookie else "calendar_session"
        key = settings.CALENDAR_ENCRYPTION_KEY
        self._cipher: Fernet | None = None
        if key:
            try:
                self._cipher = Fernet(key.get_secret_value().encode())
            except ValueError:
                pass
        secret = settings.GOOGLE_CALENDAR_CLIENT_SECRET
        self.google = GoogleCalendarProvider(
            http,
            client_id=settings.GOOGLE_CALENDAR_CLIENT_ID,
            client_secret=secret.get_secret_value() if secret else "",
            redirect_uri=settings.GOOGLE_CALENDAR_REDIRECT_URI,
        )
        self.apple = AppleCalendarProvider(http)
        self._locks: WeakValueDictionary[tuple[str, str], asyncio.Lock] = WeakValueDictionary()

    def _lock(self, session_id: str, provider: str) -> asyncio.Lock:
        key = (session_id, provider)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def ensure_ready(self) -> None:
        if self._cipher is None:
            raise CalendarError(
                "not_configured",
                "Configure a valid CALENDAR_ENCRYPTION_KEY before connecting calendars.",
            )
        try:
            await self.repository.initialize()
        except SQLAlchemyError as exc:
            raise CalendarError(
                "not_configured",
                "Calendar storage is unavailable. Check DATABASE_URL and database permissions.",
            ) from exc

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def _encrypt(self, owner: str, provider: str, values: dict[str, str]) -> str:
        if self._cipher is None:
            raise CalendarError("not_configured", "Calendar encryption is not configured.")
        payload = json.dumps({"owner": owner, "provider": provider, "values": values}).encode()
        return self._cipher.encrypt(payload).decode()

    def _decrypt(self, owner: str, provider: str, ciphertext: str) -> dict[str, str]:
        if self._cipher is None:
            raise CalendarError("not_configured", "Calendar encryption is not configured.")
        try:
            data = json.loads(self._cipher.decrypt(ciphertext.encode()))
            if (
                not isinstance(data, dict)
                or data.get("owner") != owner
                or data.get("provider") != provider
            ):
                raise ValueError("Credential ownership mismatch")
            values = data.get("values")
            if not isinstance(values, dict) or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in values.items()
            ):
                raise ValueError("Invalid saved credentials")
            return cast(dict[str, str], values)
        except (InvalidToken, ValueError, TypeError) as exc:
            raise CalendarError(
                "unauthorized",
                "Saved calendar credentials are unreadable. Disconnect and reconnect this account.",
            ) from exc

    async def session(
        self, token: str | None, *, create: bool = False
    ) -> tuple[CalendarBrowserSession, str | None]:
        await self.ensure_ready()
        if token and len(token) <= 128:
            existing = await self.repository.session(self._hash(token))
            if existing is not None and existing.expires_at > int(time.time()):
                return existing, None
        if not create:
            raise CalendarError(
                "unauthorized", "Your calendar session expired. Reload and connect again."
            )
        token = secrets.token_urlsafe(32)
        session = CalendarBrowserSession(
            id=self._hash(token),
            csrf_token=secrets.token_urlsafe(32),
            expires_at=int(time.time()) + SESSION_SECONDS,
        )
        await self.repository.create_session(session)
        return session, token

    @staticmethod
    def validate_csrf(session: CalendarBrowserSession, supplied: str | None) -> None:
        if supplied is None or not hmac.compare_digest(session.csrf_token, supplied):
            raise CalendarError(
                "forbidden", "Calendar request could not be verified. Reload and try again."
            )

    async def status(self, session: CalendarBrowserSession) -> CalendarSessionResponse:
        connections = await self.repository.connections(session.id)
        return CalendarSessionResponse(
            csrf_token=session.csrf_token,
            google_configured=self.google.configured,
            connections=[
                CalendarConnectionInfo(
                    provider=cast(CalendarProvider, connection.provider),
                    account=connection.account,
                    connected_at=datetime.fromtimestamp(connection.connected_at, UTC),
                )
                for connection in connections
            ],
        )

    async def start_google(self, session: CalendarBrowserSession) -> str:
        if not self.google.configured:
            raise CalendarError(
                "not_configured", "Configure the Google Calendar OAuth client before signing in."
            )
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        await self.repository.save_state(
            CalendarOAuthState(
                state_hash=self._hash(state),
                session_id=session.id,
                verifier_ciphertext=self._encrypt(
                    session.id, "google-oauth", {"verifier": verifier}
                ),
                expires_at=int(time.time()) + 600,
            )
        )
        return self.google.authorization_url(state, verifier)

    async def finish_google(
        self, session: CalendarBrowserSession, *, state: str, code: str | None, denied: bool
    ) -> bool:
        if not state or len(state) > 256:
            raise CalendarError(
                "forbidden", "Invalid Google authorization state. Start sign-in again."
            )
        flow = await self.repository.consume_state(self._hash(state), session.id)
        if flow is None or flow.expires_at <= int(time.time()):
            raise CalendarError(
                "forbidden", "Google sign-in expired or was already used. Start again."
            )
        if denied:
            return False
        if not code:
            raise CalendarError(
                "invalid_request", "Google did not supply an authorization code. Start again."
            )
        verifier = self._decrypt(session.id, "google-oauth", flow.verifier_ciphertext)["verifier"]
        async with self._lock(session.id, "google"):
            credentials = await self.google.exchange_code(code, verifier)
            account = credentials.get("account", "Google Calendar")
            await self._save(session.id, "google", account, credentials)
        return True

    async def connect_apple(
        self, session: CalendarBrowserSession, request: AppleConnectRequest
    ) -> None:
        password = request.app_password.get_secret_value().strip()
        email = request.email.strip()
        if not re.fullmatch(r"[A-Za-z0-9]{4}(?:-[A-Za-z0-9]{4}){3}", password):
            raise CalendarError(
                "invalid_request",
                "Use an Apple app-specific password (xxxx-xxxx-xxxx-xxxx), "
                "not your Apple password.",
            )
        if "@" not in email or any(character.isspace() for character in email):
            raise CalendarError("invalid_request", "Enter the email address of your Apple Account.")
        async with self._lock(session.id, "apple"):
            _, credentials = await self.apple.list_calendars(
                {"username": email, "app_password": password}
            )
            await self._save(session.id, "apple", email, credentials)

    async def _save(
        self,
        owner: str,
        provider: CalendarProvider,
        account: str,
        credentials: dict[str, str],
        *,
        connected_at: int | None = None,
    ) -> None:
        await self.repository.save_connection(
            CalendarConnection(
                session_id=owner,
                provider=provider,
                account=account,
                credentials_ciphertext=self._encrypt(owner, provider, credentials),
                connected_at=connected_at if connected_at is not None else int(time.time()),
            )
        )

    async def _connection(
        self, owner: str, provider: CalendarProvider
    ) -> tuple[CalendarConnection, dict[str, str]]:
        connection = await self.repository.connection(owner, provider)
        if connection is None:
            raise CalendarError("unauthorized", "Connect this calendar account first.")
        return connection, self._decrypt(owner, provider, connection.credentials_ciphertext)

    async def calendars(
        self, session: CalendarBrowserSession, provider: CalendarProvider
    ) -> list[CalendarInfo]:
        async with self._lock(session.id, provider):
            connection, credentials = await self._connection(session.id, provider)
            adapter = self.google if provider == "google" else self.apple
            calendars, updated = await adapter.list_calendars(credentials)
            if updated != credentials:
                await self._save(
                    session.id,
                    provider,
                    connection.account,
                    updated,
                    connected_at=connection.connected_at,
                )
            return calendars

    async def parse(
        self,
        session: CalendarBrowserSession,
        provider: CalendarProvider,
        request: CalendarParseRequest,
    ) -> ParsedCalendarResponse:
        timezone = ZoneInfo(request.timezone)
        start = datetime.combine(request.start, midnight(), timezone)
        end = datetime.combine(request.end + timedelta(days=1), midnight(), timezone)
        parsed: list[ParsedCalendarEvent] = []
        async with self._lock(session.id, provider):
            connection, credentials = await self._connection(session.id, provider)
            adapter = self.google if provider == "google" else self.apple
            calendars, credentials = await adapter.list_calendars(credentials)
            await self._save(
                session.id,
                provider,
                connection.account,
                credentials,
                connected_at=connection.connected_at,
            )
            available = {calendar.id: calendar for calendar in calendars}
            if any(calendar_id not in available for calendar_id in request.calendar_ids):
                raise CalendarError(
                    "forbidden", "A selected calendar is not available to this connected account."
                )
            for calendar_id in request.calendar_ids:
                calendar, credentials = await adapter.fetch_calendar(
                    credentials, calendar_id, start, end
                )
                # Save refreshed credentials before parsing or fetching another calendar can fail.
                await self._save(
                    session.id,
                    provider,
                    connection.account,
                    credentials,
                    connected_at=connection.connected_at,
                )
                parsed.extend(
                    await self._events(
                        calendar, request, provider, calendar_id, available[calendar_id].name
                    )
                )
        parsed.sort(key=lambda event: (event.start, event.id))
        return ParsedCalendarResponse(
            provider=provider,
            start=request.start,
            end=request.end,
            timezone=request.timezone,
            events=parsed,
        )

    @staticmethod
    async def _events(
        calendar: icalendar.Calendar,
        window: CalendarWindow,
        source: CalendarSource,
        calendar_id: str,
        calendar_name: str,
    ) -> list[ParsedCalendarEvent]:
        try:
            events = await asyncio.to_thread(
                expand_events, calendar, window.start, window.end, ZoneInfo(window.timezone)
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise CalendarError(
                "upstream", "The calendar returned data the parser could not read."
            ) from exc
        return [
            ParsedCalendarEvent.model_validate(
                {
                    **event.to_dict(),
                    "provider": source,
                    "calendar_id": calendar_id,
                    "calendar_name": calendar_name,
                    "id": f"{source}:{quote(calendar_id, safe='')}:{event.id}",
                }
            )
            for event in events
        ]

    async def import_url(
        self, session: CalendarBrowserSession, request: CalendarUrlImportRequest
    ) -> ParsedCalendarResponse:
        calendar_id = google_calendar_id(request.url)
        source_url = request.url
        if calendar_id is not None:
            if self.google.configured and await self.repository.connection(session.id, "google"):
                calendars = await self.calendars(session, "google")
                match = next(
                    (
                        item
                        for item in calendars
                        if item.id == calendar_id or (calendar_id == "primary" and item.primary)
                    ),
                    None,
                )
                if match is not None:
                    return await self.parse(
                        session,
                        "google",
                        CalendarParseRequest(
                            calendar_ids=[match.id],
                            start=request.start,
                            end=request.end,
                            timezone=request.timezone,
                        ),
                    )
            source_url = (
                "https://calendar.google.com/calendar/ical/"
                f"{quote(calendar_id, safe='')}/public/basic.ics"
            )
        calendar = await fetch_calendar_feed(source_url)
        source_id = self._hash(source_url)
        name = str(calendar.get("X-WR-CALNAME", "")).strip() or "Imported calendar"
        events = await self._events(calendar, request, "url", source_id, name)
        return ParsedCalendarResponse(
            provider="url",
            start=request.start,
            end=request.end,
            timezone=request.timezone,
            events=events,
        )

    async def disconnect(self, session: CalendarBrowserSession, provider: CalendarProvider) -> None:
        async with self._lock(session.id, provider):
            await self.repository.disconnect(session.id, provider)
