from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from shared.jobs.domain.job import JobEntityType, JobKind


class JobTracker(Protocol):
    """Write port that producing contexts use to record async work.

    See ADR-012 §5. Four methods, all idempotent on terminal status of
    the same kind. Cross-terminal transitions raise
    `InvalidJobTransitionError`.
    """

    async def start(
        self,
        *,
        organization_id: UUID,
        requested_by_user_id: UUID,
        kind: JobKind,
        entity_type: JobEntityType,
        entity_id: UUID,
        title: str,
    ) -> UUID: ...

    async def complete(
        self,
        job_id: UUID,
        result_summary: dict[str, Any] | None = None,
    ) -> None: ...

    async def fail(
        self,
        job_id: UUID,
        error_code: str,
        error_message: str,
    ) -> None: ...

    async def update_entity_id(self, job_id: UUID, entity_id: UUID) -> None: ...
