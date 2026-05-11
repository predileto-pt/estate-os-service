"""Get session view — read-side use case with debounced `last_seen_at` refresh."""

from __future__ import annotations

from datetime import datetime

from sessions.application.ports.clock import Clock
from sessions.application.ports.session_repository import SessionRepository
from sessions.domain.models.session import Session


class GetSessionView:
    def __init__(self, repo: SessionRepository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    async def execute(self, session: Session, *, debounce_seconds: int) -> Session:
        now = self._clock.now()
        if _seconds_since(session.last_seen_at, now) <= debounce_seconds:
            return session
        refreshed = session.touched(now=now)
        await self._repo.update(refreshed)
        return refreshed


def _seconds_since(then: datetime, now: datetime) -> float:
    return (now - then).total_seconds()
