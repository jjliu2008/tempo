"""Wire shapes for workload analysis (the same JSON as `python -m hellweek analyze`)."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class InputEvent(BaseModel):
    """An already-expanded occurrence, e.g. from POST /calendars/{provider}/parse.
    Extra fields (location, description, calendar ids) are accepted and dropped."""

    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool = False


class CalendarAnalyzeRequest(BaseModel):
    """Exactly one source: the built-in demo semester, raw .ics text, a calendar
    URL, or events another endpoint already parsed. The URL is a password; it only
    ever travels in this body. Size and format checks happen in the service so
    error messages never echo it.
    """

    model_config = ConfigDict(extra="forbid")

    source: Literal["demo", "ics", "url", "events"]
    ics: str | None = None
    url: str | None = None
    events: list[InputEvent] | None = None
    start: date | None = None
    end: date | None = None
    tz: str | None = None
    gemma: bool = True


class BreakdownItem(BaseModel):
    event_id: str
    title: str
    kind: Literal["scheduled", "prep"]
    hours: float


class Day(BaseModel):
    date: date
    scheduled_hours: float
    prep_hours: float
    total_hours: float
    breakdown: list[BreakdownItem]


class KeyEvent(BaseModel):
    event_id: str
    title: str
    type: str
    date: date
    prep_hours: float
    stress: int


class Report(BaseModel):
    headline: str
    forecast: str
    advisories: list[str]
    source: Literal["gemma", "template"]


class HellWeek(BaseModel):
    start: date
    end: date
    total_hours: float
    peak_start: date
    peak_end: date
    peak_hours: float
    key_events: list[KeyEvent]
    report: Report | None = None


class AnalyzedEvent(BaseModel):
    id: str
    title: str
    start: str
    end: str
    all_day: bool
    type: str
    prep_hours: float
    stress: int


class PrepBlock(BaseModel):
    event_id: str
    title: str
    date: date
    start_hour: float
    end_hour: float


class Meta(BaseModel):
    start: date | None
    end: date | None
    timezone: str
    threshold_hours: float
    median_weekly_hours: float
    classifier: Literal["gemma", "keywords"]
    unplaced_prep_hours: float


class CalendarAnalysis(BaseModel):
    meta: Meta
    days: list[Day]
    hell_weeks: list[HellWeek]
    events: list[AnalyzedEvent]
    prep_blocks: list[PrepBlock]
