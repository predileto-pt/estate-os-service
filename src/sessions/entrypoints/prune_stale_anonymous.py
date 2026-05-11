"""CLI entrypoint: prune stale anonymous sessions in the portal DB.

Invocation:

    uv run python -m sessions.entrypoints.prune_stale_anonymous

Bootstraps a minimal `SessionsContainer` (portal engine + session maker
only — no FastAPI, no cookie signer, no auth wiring), runs the use case,
prints `{deleted_count, duration_ms}` JSON to stdout, exits 0 on success.
"""

from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker

from sessions.adapters.database.repository import SqlAlchemySessionRepository
from sessions.application.use_cases.prune_stale_anonymous_sessions import (
    PruneStaleAnonymousSessions,
)
from shared.config import settings
from shared.database.engine import build_async_engine


async def main() -> int:
    if not settings.portal_database_url:
        print("ERROR: PORTAL_DATABASE_URL is empty", file=sys.stderr)
        return 2

    engine = build_async_engine(settings.portal_database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    repo = SqlAlchemySessionRepository(session_maker)
    use_case = PruneStaleAnonymousSessions(repo, ttl_days=settings.session_anonymous_ttl_days)

    try:
        result = await use_case.execute()
    finally:
        await engine.dispose()

    print(json.dumps({"deleted_count": result.deleted_count, "duration_ms": result.duration_ms}))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
