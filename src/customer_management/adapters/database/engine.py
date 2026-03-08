from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from customer_management.config import Settings


def build_async_engine(database_url: str | None = None) -> AsyncEngine:
    url = database_url or Settings().database_url
    if not url:
        raise ValueError("DATABASE_URL must be set")
    return create_async_engine(url, echo=False)
