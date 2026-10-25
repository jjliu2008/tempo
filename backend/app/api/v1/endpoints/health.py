"""Liveness endpoint used by local dev, load balancers and container probes."""

from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "environment": settings.ENVIRONMENT,
        "version": settings.VERSION,
    }
