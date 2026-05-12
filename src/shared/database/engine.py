from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from shared.config import Settings


def build_async_engine(database_url: str | None = None) -> AsyncEngine:
    url = database_url or Settings().database_url
    if not url:
        raise ValueError("DATABASE_URL must be set")
    # Supabase's transaction pooler aggressively closes idle connections;
    # pool_pre_ping + recycle avoid handing out a dead conn after idle.
    return create_async_engine(
        url, echo=False, pool_pre_ping=True, pool_recycle=300
    )
