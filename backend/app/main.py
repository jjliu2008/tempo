"""Application entrypoint.

Run locally with: uvicorn app.main:app --reload --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import async_session_factory, engine
from app.repositories.calendar import CalendarRepository
from app.services.calendar import CalendarService
from app.services.calendar_errors import CalendarError
from app.services.gemma import GemmaError, GemmaService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    key = settings.GOOGLE_API_KEY
    service = GemmaService(settings) if key and key.get_secret_value().strip() else None
    app.state.gemma = service
    calendar_http = httpx.AsyncClient(timeout=30, follow_redirects=False)
    app.state.calendars = CalendarService(
        settings, CalendarRepository(engine, async_session_factory), calendar_http
    )
    try:
        yield
    finally:
        await calendar_http.aclose()
        await engine.dispose()
        if service is not None:
            await service.aclose()


def create_app() -> FastAPI:
    configure_logging()

    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # All versioned endpoints live under /api/v1.
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.exception_handler(GemmaError)
    async def gemma_error_handler(_request: Request, error: GemmaError) -> JSONResponse:
        status_codes = {
            "not_configured": 503,
            "invalid_request": 400,
            "rate_limited": 429,
            "timeout": 504,
            "blocked": 422,
            "provider": 502,
        }
        return JSONResponse(
            status_code=status_codes[error.kind],
            content={"detail": {"code": f"gemma_{error.kind}", "message": str(error)}},
        )

    @app.exception_handler(CalendarError)
    async def calendar_error_handler(_request: Request, error: CalendarError) -> JSONResponse:
        statuses = {
            "not_configured": 503,
            "invalid_request": 400,
            "unauthorized": 401,
            "forbidden": 403,
            "upstream": 502,
            "timeout": 504,
        }
        return JSONResponse(
            status_code=statuses[error.kind],
            content={"detail": {"code": f"calendar_{error.kind}", "message": str(error)}},
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        if not request.url.path.startswith(f"{settings.API_V1_PREFIX}/calendars"):
            return await request_validation_exception_handler(request, error)
        # Pydantic's default `input` fields can echo an app-specific password.
        errors = [
            {key: value for key, value in entry.items() if key in ("loc", "msg", "type")}
            for entry in error.errors()
        ]
        return JSONResponse(
            status_code=422, content={"detail": errors}, headers={"Cache-Control": "no-store"}
        )

    return app


app = create_app()
