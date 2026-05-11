"""In-memory `SessionRepository` for tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sessions.application.ports.session_repository import SessionRepository
from sessions.domain.models.session import Session, SessionKind
from sessions.domain.value_objects import SessionId


class InMemorySessionRepository(SessionRepository):
    def __init__(self) -> None:
        self._rows: dict[SessionId, Session] = {}

    async def get_by_id(self, session_id: SessionId) -> Session | None:
        return self._rows.get(session_id)

    async def save(self, session: Session) -> Session:
        self._rows[session.id] = session
        return session

    async def update(self, session: Session) -> Session:
        self._rows[session.id] = session
        return session

    async def prune_stale_anonymous(self, ttl_days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        stale = [
            sid
            for sid, s in self._rows.items()
            if s.kind == SessionKind.ANONYMOUS and s.last_seen_at < cutoff
        ]
        for sid in stale:
            del self._rows[sid]
        return len(stale)
