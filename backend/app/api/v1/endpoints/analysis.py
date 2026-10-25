"""Workload analysis: daily load, hell weeks, Gemma forecasts and study blocks."""

from typing import Any

from fastapi import APIRouter, HTTPException
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.schemas.analysis import CalendarAnalysis, CalendarAnalyzeRequest
from app.services.analysis import CalendarRequestError, analyze_calendar
from hellweek.parse import CalendarSourceError

router = APIRouter()


@router.post("", response_model=CalendarAnalysis)
async def analyze(body: CalendarAnalyzeRequest) -> dict[str, Any]:
    """A first Gemma run on a calendar can take about 30 s; repeat titles are cached."""
    try:
        return await run_in_threadpool(analyze_calendar, body, settings)
    except (CalendarRequestError, CalendarSourceError) as exc:
        raise HTTPException(
            status_code=400, detail={"code": "calendar_invalid", "message": str(exc)}
        ) from None
