"""Init session use case — mint a new anonymous session."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sessions.application.ports.clock import Clock
from sessions.application.ports.session_repository import SessionRepository
from sessions.domain.models.session import Session, SessionKind
from sessions.domain.value_objects import SessionId


@dataclass(frozen=True)
class InitSessionResult:
    session: Session
    minted: bool  # True if a new row was inserted; False if the cookie was already valid


class InitSession:
    def __init__(self, repo: SessionRepository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    async def execute(
        self, *, existing: Session | None = None, debounce_seconds: int = 60
    ) -> InitSessionResult:
        now = self._clock.now()
        if existing is not None and not existing.revoked:
            # Debounced last_seen_at refresh.
            if _seconds_since(existing.last_seen_at, now) > debounce_seconds:
                refreshed = existing.touched(now=now)
                await self._repo.update(refreshed)
                return InitSessionResult(session=refreshed, minted=False)
            return InitSessionResult(session=existing, minted=False)

        fresh = Session(
            id=SessionId(uuid4()),
            kind=SessionKind.ANONYMOUS,
            user_id=None,
            favorites=frozenset(),
            prefs={},
            created_at=now,
            last_seen_at=now,
            claimed_at=None,
            revoked=False,
        )
        saved = await self._repo.save(fresh)
        return InitSessionResult(session=saved, minted=True)


def _seconds_since(then: datetime, now: datetime) -> float:
    return (now - then).total_seconds()
