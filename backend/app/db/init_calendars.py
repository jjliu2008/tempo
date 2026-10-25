"""Create calendar tables before launching multiple workers: python -m app.db.init_calendars."""

import asyncio

from app.db.session import async_session_factory, engine
from app.repositories.calendar import CalendarRepository


async def main() -> None:
    try:
        await CalendarRepository(engine, async_session_factory).initialize()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
