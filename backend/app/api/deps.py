"""Shared FastAPI dependencies. Import these with `Depends(...)` in endpoints."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory
from app.services.agent_orchestrator import AgentOrchestrator
from app.services.calendar import CalendarService
from app.services.calendar_errors import CalendarError
from app.services.gemma import GemmaError, GemmaService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


def get_gemma_service(request: Request) -> GemmaService:
    service = getattr(request.app.state, "gemma", None)
    if not isinstance(service, GemmaService):
        raise GemmaError("not_configured", "Set GOOGLE_API_KEY to enable Gemma.")
    return service


def get_agent_orchestrator(
    gemma: Annotated[GemmaService, Depends(get_gemma_service)],
) -> AgentOrchestrator:
    return AgentOrchestrator(gemma)


def get_calendar_service(request: Request) -> CalendarService:
    service = getattr(request.app.state, "calendars", None)
    if not isinstance(service, CalendarService):
        raise CalendarError("not_configured", "Calendar connections are unavailable.")
    return service


# Add auth dependencies here, e.g.:
# async def get_current_user(token: str = Depends(oauth2_scheme),
#                            db: AsyncSession = Depends(get_db)) -> User: ...
