import asyncio
import os
import subprocess

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from core_api.adapters.database.repositories import (
    SqlAlchemyCompanyRepository,
    SqlAlchemyNotificationRepository,
    SqlAlchemySubscriptionRepository,
    SqlAlchemyUserRepository,
)

# ── Container + Engine (session-scoped) ──────────────────────────────────────


@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("postgres:16") as pg:
        url = pg.get_connection_url()
        async_url = url.replace("psycopg2", "asyncpg")

        # Create stub auth schema/functions so RLS policies in the migration work
        async def _create_auth_stubs():
            eng = create_async_engine(async_url, poolclass=NullPool)
            async with eng.begin() as conn:
                await conn.execute(text("CREATE SCHEMA IF NOT EXISTS auth;"))
                await conn.execute(text(
                    "CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid "
                    "LANGUAGE sql STABLE AS $$ "
                    "SELECT '00000000-0000-0000-0000-000000000000'::uuid; $$;"
                ))
                await conn.execute(text(
                    "CREATE OR REPLACE FUNCTION auth.role() RETURNS text "
                    "LANGUAGE sql STABLE AS $$ "
                    "SELECT 'service_role'::text; $$;"
                ))
            await eng.dispose()

        asyncio.run(_create_auth_stubs())

        # Run Alembic migrations via subprocess (env.py uses asyncpg internally)
        env = {**os.environ, "DATABASE_URL": async_url}
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            env=env,
            check=True,
            capture_output=True,
        )

        yield async_url


@pytest.fixture(scope="session")
def engine(postgres_url):
    eng = create_async_engine(postgres_url, poolclass=NullPool)
    yield eng
    asyncio.run(eng.dispose())


# ── Session (function-scoped, rolled back after each test) ───────────────────


@pytest.fixture
async def session(engine):
    conn = await engine.connect()
    trans = await conn.begin()
    async_session = AsyncSession(bind=conn, expire_on_commit=False)
    try:
        yield async_session
    finally:
        await async_session.close()
        await trans.rollback()
        await conn.close()


# ── Repository fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def company_repo(session):
    return SqlAlchemyCompanyRepository(session)


@pytest.fixture
def user_repo(session):
    return SqlAlchemyUserRepository(session)


@pytest.fixture
def subscription_repo(session):
    return SqlAlchemySubscriptionRepository(session)


@pytest.fixture
def notification_repo(session):
    return SqlAlchemyNotificationRepository(session)
