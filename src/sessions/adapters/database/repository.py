"""SQLAlchemy-backed `SessionRepository` against the portal DB."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sessions.adapters.database.models import SessionModel
from sessions.application.ports.session_repository import SessionRepository
from sessions.domain.models.session import Session, SessionKind
from sessions.domain.value_objects import SessionId


class SqlAlchemySessionRepository(SessionRepository):
    def __init__(self, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self._session_maker = session_maker

    async def get_by_id(self, session_id: SessionId) -> Session | None:
        async with self._session_maker() as db:
            row = await db.get(SessionModel, str(session_id))
            if row is None:
                return None
            return _to_domain(row)

    async def save(self, session: Session) -> Session:
        async with self._session_maker() as db:
            db.add(_to_row(session))
            await db.commit()
            return session

    async def update(self, session: Session) -> Session:
        async with self._session_maker() as db:
            row = await db.get(SessionModel, str(session.id))
            if row is None:
                # Caller passed a session not in DB — should not happen in normal flow.
                db.add(_to_row(session))
                await db.commit()
                return session
            row.kind = session.kind.value
            row.user_id = str(session.user_id) if session.user_id is not None else None
            row.favorites = [str(pid) for pid in session.favorites]
            row.prefs = dict(session.prefs)
            row.last_seen_at = session.last_seen_at
            row.claimed_at = session.claimed_at
            row.revoked = session.revoked
            await db.commit()
            return session

    async def prune_stale_anonymous(self, ttl_days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        async with self._session_maker() as db:
            stmt = delete(SessionModel).where(
                SessionModel.kind == SessionKind.ANONYMOUS.value,
                SessionModel.last_seen_at < cutoff,
            )
            result = await db.execute(stmt)
            await db.commit()
            return int(result.rowcount or 0)


def _to_domain(row: SessionModel) -> Session:
    favorites = frozenset(UUID(pid) for pid in (row.favorites or []))
    return Session(
        id=SessionId(UUID(row.id)),
        kind=SessionKind(row.kind),
        user_id=UUID(row.user_id) if row.user_id else None,
        favorites=favorites,
        prefs=dict(row.prefs or {}),
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        claimed_at=row.claimed_at,
        revoked=row.revoked,
    )


def _to_row(session: Session) -> SessionModel:
    return SessionModel(
        id=str(session.id),
        kind=session.kind.value,
        user_id=str(session.user_id) if session.user_id is not None else None,
        favorites=[str(pid) for pid in session.favorites],
        prefs=dict(session.prefs),
        created_at=session.created_at,
        last_seen_at=session.last_seen_at,
        claimed_at=session.claimed_at,
        revoked=session.revoked,
    )
