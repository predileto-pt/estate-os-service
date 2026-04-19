import asyncio
from logging.config import fileConfig
from urllib.parse import quote_plus, urlparse

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from shared.config import Settings
from shared.database.models import Base
import bookings.adapters.database.models  # noqa: F401 — register models for autogenerate
import contract_intelligence.adapters.database.models  # noqa: F401 — register models for autogenerate
import identity.adapters.database.models  # noqa: F401 — register models for autogenerate
import organizations.adapters.database.models  # noqa: F401 — register models for autogenerate
import properties.adapters.database.models  # noqa: F401 — register models for autogenerate
import screening.adapters.database.models  # noqa: F401 — register models for autogenerate

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _encode_database_url(raw_url: str) -> str:
    """Percent-encode the password in a DATABASE_URL so special chars like @ are safe."""
    parsed = urlparse(raw_url)
    if parsed.password:
        encoded_password = quote_plus(parsed.password)
        # Rebuild netloc with encoded password
        userinfo = f"{parsed.username}:{encoded_password}"
        host_part = parsed.hostname
        if parsed.port:
            host_part = f"{host_part}:{parsed.port}"
        netloc = f"{userinfo}@{host_part}"
        return parsed._replace(netloc=netloc).geturl()
    return raw_url


# Load DATABASE_URL from settings into alembic config
settings = Settings()
if settings.database_url:
    # Escape % as %% for configparser interpolation
    safe_url = _encode_database_url(settings.database_url).replace("%", "%%")
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


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
