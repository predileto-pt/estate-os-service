from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from shared.jobs.application.ports.job_repository import JobRepository
from shared.jobs.domain.exceptions import JobNotFoundError

log = structlog.get_logger()

# Soft cap on `result_summary` payload size — ADR-012 §10.
RESULT_SUMMARY_SOFT_CAP_BYTES = 4 * 1024


class CompleteJob:
    def __init__(self, job_repo: JobRepository) -> None:
        self.job_repo = job_repo

    async def execute(
        self,
        job_id: UUID,
        result_summary: dict[str, Any] | None = None,
    ) -> None:
        job = await self.job_repo.get_by_id(job_id)
        if job is None:
            raise JobNotFoundError(str(job_id))

        capped = _enforce_summary_cap(result_summary, job_id=job_id)
        job.mark_completed(capped)
        await self.job_repo.update(job)


def _enforce_summary_cap(summary: dict[str, Any] | None, *, job_id: UUID) -> dict[str, Any] | None:
    if summary is None:
        return None
    encoded = json.dumps(summary, default=str).encode("utf-8")
    if len(encoded) <= RESULT_SUMMARY_SOFT_CAP_BYTES:
        return summary
    log.warning(
        "jobs.result_summary_truncated",
        job_id=str(job_id),
        encoded_bytes=len(encoded),
        cap_bytes=RESULT_SUMMARY_SOFT_CAP_BYTES,
    )
    return {
        "_truncated": True,
        "_original_bytes": len(encoded),
    }
