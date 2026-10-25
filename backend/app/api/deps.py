"""Shared FastAPI dependencies. Import these with `Depends(...)` in endpoints."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


# Add auth dependencies here, e.g.:
# async def get_current_user(token: str = Depends(oauth2_scheme),
#                            db: AsyncSession = Depends(get_db)) -> User: ...
