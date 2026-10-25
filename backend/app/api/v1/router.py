"""Aggregate every v1 endpoint router in one place."""

from fastapi import APIRouter

from app.api.v1.endpoints import health

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])

# Add feature routers here:
# api_router.include_router(users.router, prefix="/users", tags=["users"])
