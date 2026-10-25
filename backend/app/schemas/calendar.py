"""Provider-neutral calendar connection and parsed-event contracts."""

from datetime import date, datetime
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

CalendarProvider = Literal["google", "apple"]
CalendarSource = Literal["google", "apple", "url"]


class CalendarInfo(BaseModel):
    id: str
    name: str
    timezone: str | None = None
    primary: bool = False


class CalendarConnectionInfo(BaseModel):
    provider: CalendarProvider
    account: str
    connected_at: datetime


class CalendarSessionResponse(BaseModel):
    csrf_token: str
    google_configured: bool
    connections: list[CalendarConnectionInfo]


class CalendarListResponse(BaseModel):
    provider: CalendarProvider
    calendars: list[CalendarInfo]


class AppleConnectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    app_password: SecretStr


class GoogleAuthorizationResponse(BaseModel):
    authorization_url: str


class CalendarWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: date
    end: date
    timezone: str

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Use an IANA timezone such as America/New_York") from exc
        return value

    @model_validator(mode="after")
    def valid_window(self) -> Self:
        if self.end < self.start:
            raise ValueError("End date must not precede start date")
        if self.end == date.max:
            raise ValueError("End date must allow an exclusive next-day boundary")
        if (self.end - self.start).days > 365:
            raise ValueError("Choose a window of at most 366 days")
        return self


class CalendarParseRequest(CalendarWindow):
    calendar_ids: list[str] = Field(min_length=1, max_length=20)

    @field_validator("calendar_ids")
    @classmethod
    def valid_ids(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values) or any(not value.strip() for value in values):
            raise ValueError("Calendar ids must be unique and not blank")
        return values


class CalendarUrlImportRequest(CalendarWindow):
    url: str = Field(min_length=1, max_length=8192)


class ParsedCalendarEvent(BaseModel):
    provider: CalendarSource
    calendar_id: str
    calendar_name: str
    id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    duration_hours: float
    location: str
    description: str


class ParsedCalendarResponse(BaseModel):
    provider: CalendarSource
    start: date
    end: date
    timezone: str
    events: list[ParsedCalendarEvent]
