"""Prune stale anonymous sessions — invoked by the CLI entrypoint daily."""

from __future__ import annotations

import time
from dataclasses import dataclass

from sessions.application.ports.session_repository import SessionRepository


@dataclass(frozen=True)
class PruneResult:
    deleted_count: int
    duration_ms: int


class PruneStaleAnonymousSessions:
    def __init__(self, repo: SessionRepository, *, ttl_days: int) -> None:
        self._repo = repo
        self._ttl_days = ttl_days

    async def execute(self) -> PruneResult:
        started = time.monotonic()
        deleted = await self._repo.prune_stale_anonymous(self._ttl_days)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return PruneResult(deleted_count=deleted, duration_ms=elapsed_ms)
