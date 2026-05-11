"""Logout — flip to anonymous and clear favorites + prefs (privacy footgun fix)."""

from __future__ import annotations

from sessions.application.ports.clock import Clock
from sessions.application.ports.session_repository import SessionRepository
from sessions.domain.models.session import Session, SessionKind


class LogoutSession:
    def __init__(self, repo: SessionRepository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    async def execute(self, session: Session) -> Session:
        now = self._clock.now()
        # Idempotent: already-anonymous session just refreshes last_seen_at.
        if (
            session.kind == SessionKind.ANONYMOUS
            and session.user_id is None
            and not session.favorites
            and not session.prefs
        ):
            return session
        cleared = session.logged_out(now=now)
        return await self._repo.update(cleared)
