"""SessionRepository port — abstract persistence interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from sessions.domain.models.session import Session
from sessions.domain.value_objects import SessionId


class SessionRepository(ABC):
    @abstractmethod
    async def get_by_id(self, session_id: SessionId) -> Session | None: ...

    @abstractmethod
    async def save(self, session: Session) -> Session:
        """Insert a new session row."""

    @abstractmethod
    async def update(self, session: Session) -> Session:
        """Update an existing session row."""

    @abstractmethod
    async def prune_stale_anonymous(self, ttl_days: int) -> int:
        """Delete anonymous sessions with `last_seen_at < now - ttl_days`. Returns deleted count."""
