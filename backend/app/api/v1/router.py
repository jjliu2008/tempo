"""Aggregate every v1 endpoint router in one place."""

from fastapi import APIRouter

from app.api.v1.endpoints import calendars, gemma, health

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(gemma.router, prefix="/gemma", tags=["gemma"])
api_router.include_router(calendars.router, prefix="/calendars", tags=["calendars"])

# Add feature routers here:
# api_router.include_router(users.router, prefix="/users", tags=["users"])
