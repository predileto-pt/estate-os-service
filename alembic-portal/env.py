"""Alembic env for the **portal** Postgres database.

Imports portal-context models only. Targets `portal_database_url`. Uses a
distinct `Base` (`sessions.adapters.database.base.Base`) so autogenerate
can't accidentally drop admin tables — the two MetaData instances are
completely independent.
"""

import asyncio
from logging.config import fileConfig
from urllib.parse import quote_plus, urlparse

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from shared.config import Settings

# Portal-scoped Base + models. Importing the model module registers tables
# against `Base.metadata` for autogenerate.
from sessions.adapters.database.base import Base
import sessions.adapters.database.models  # noqa: F401 — register sessions table

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _encode_database_url(raw_url: str) -> str:
    """Percent-encode the password in a DATABASE_URL so special chars like @ are safe."""
    parsed = urlparse(raw_url)
    if parsed.password:
        encoded_password = quote_plus(parsed.password)
        userinfo = f"{parsed.username}:{encoded_password}"
        host_part = parsed.hostname
        if parsed.port:
            host_part = f"{host_part}:{parsed.port}"
        netloc = f"{userinfo}@{host_part}"
        return parsed._replace(netloc=netloc).geturl()
    return raw_url


settings = Settings()
if settings.portal_database_url:
    safe_url = _encode_database_url(settings.portal_database_url).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", safe_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online_async() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_migrations_online_async())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
