"""Aggregate every v1 endpoint router in one place."""

from fastapi import APIRouter

from app.api.v1.endpoints import analysis, calendars, gemma, health

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(gemma.router, prefix="/gemma", tags=["gemma"])
api_router.include_router(calendars.router, prefix="/calendars", tags=["calendars"])
api_router.include_router(analysis.router, prefix="/analysis", tags=["analysis"])

# Add feature routers here:
# api_router.include_router(users.router, prefix="/users", tags=["users"])
