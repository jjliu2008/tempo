"""SQL operations for browser-owned calendar connections."""

import asyncio
import time

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.base import Base
from app.models.calendar import CalendarBrowserSession, CalendarConnection, CalendarOAuthState


class CalendarRepository:
    def __init__(self, engine: AsyncEngine, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._engine = engine
        self._sessions = sessions
        self._initialized = False
        self._initializing = asyncio.Lock()

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initializing:
            if not self._initialized:
                async with self._engine.begin() as connection:
                    await connection.run_sync(
                        lambda sync: Base.metadata.create_all(
                            sync,
                            tables=[
                                Base.metadata.tables[CalendarBrowserSession.__tablename__],
                                Base.metadata.tables[CalendarConnection.__tablename__],
                                Base.metadata.tables[CalendarOAuthState.__tablename__],
                            ],
                        )
                    )
                self._initialized = True

    async def session(self, session_id: str) -> CalendarBrowserSession | None:
        async with self._sessions() as db:
            return await db.get(CalendarBrowserSession, session_id)

    async def create_session(self, session: CalendarBrowserSession) -> None:
        async with self._sessions.begin() as db:
            expired = select(CalendarBrowserSession.id).where(
                CalendarBrowserSession.expires_at <= int(time.time())
            )
            await db.execute(
                delete(CalendarConnection).where(CalendarConnection.session_id.in_(expired))
            )
            await db.execute(
                delete(CalendarOAuthState).where(CalendarOAuthState.session_id.in_(expired))
            )
            await db.execute(
                delete(CalendarBrowserSession).where(CalendarBrowserSession.id.in_(expired))
            )
            await db.execute(
                delete(CalendarOAuthState).where(CalendarOAuthState.expires_at <= int(time.time()))
            )
            db.add(session)

    async def connections(self, session_id: str) -> list[CalendarConnection]:
        async with self._sessions() as db:
            return list(
                await db.scalars(
                    select(CalendarConnection)
                    .where(CalendarConnection.session_id == session_id)
                    .order_by(CalendarConnection.provider)
                )
            )

    async def connection(self, session_id: str, provider: str) -> CalendarConnection | None:
        async with self._sessions() as db:
            return await db.get(CalendarConnection, (session_id, provider))

    async def save_connection(self, connection: CalendarConnection) -> None:
        async with self._sessions.begin() as db:
            await db.merge(connection)

    async def disconnect(self, session_id: str, provider: str) -> None:
        async with self._sessions.begin() as db:
            await db.execute(
                delete(CalendarConnection).where(
                    CalendarConnection.session_id == session_id,
                    CalendarConnection.provider == provider,
                )
            )

    async def save_state(self, state: CalendarOAuthState) -> None:
        async with self._sessions.begin() as db:
            await db.execute(
                delete(CalendarOAuthState).where(CalendarOAuthState.session_id == state.session_id)
            )
            db.add(state)

    async def consume_state(self, state_hash: str, session_id: str) -> CalendarOAuthState | None:
        async with self._sessions.begin() as db:
            # Atomic DELETE RETURNING makes replay fail even with simultaneous callbacks.
            result = await db.execute(
                delete(CalendarOAuthState)
                .where(
                    CalendarOAuthState.state_hash == state_hash,
                    CalendarOAuthState.session_id == session_id,
                )
                .returning(CalendarOAuthState)
            )
            return result.scalar_one_or_none()
