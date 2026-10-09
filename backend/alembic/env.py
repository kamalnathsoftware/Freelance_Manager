import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  (register models)
from alembic import context
from app.core.config import get_settings
from app.core.db import Base

target_metadata = Base.metadata
url = get_settings().database_url


def _run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=True,  # SQLite (tests/dev) cannot ALTER constraints; no-op on Postgres
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
