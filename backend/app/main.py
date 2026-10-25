"""Application entrypoint.

Run locally with: uvicorn app.main:app --reload --port 8000
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.services.gemma import GemmaError, GemmaService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    key = settings.GOOGLE_API_KEY
    service = GemmaService(settings) if key and key.get_secret_value().strip() else None
    app.state.gemma = service
    try:
        yield
    finally:
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

    return app


app = create_app()
