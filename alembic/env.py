import asyncio
import os

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.core import models  # noqa: F401
from app.core.db import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=os.environ["DATABASE_URL"],
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def sync_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    section = {"sqlalchemy.url": os.environ["DATABASE_URL"]}
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(sync_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
