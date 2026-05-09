from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from supabase import AsyncClient

from shared.jobs.application.ports.job_repository import JobRepository
from shared.jobs.domain.job import Job, JobEntityType, JobKind, JobStatus


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_required_datetime(value: str | datetime) -> datetime:
    parsed = _parse_datetime(value)
    if parsed is None:
        raise ValueError("required datetime is null")
    return parsed


class SupabaseJobRepository(JobRepository):
    TABLE = "background_jobs"

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    @staticmethod
    def _to_domain(row: dict[str, Any]) -> Job:
        return Job(
            id=UUID(row["id"]),
            organization_id=UUID(row["organization_id"]),
            requested_by_user_id=UUID(row["requested_by_user_id"]),
            kind=JobKind(row["kind"]),
            status=JobStatus(row["status"]),
            entity_type=JobEntityType(row["entity_type"]),
            entity_id=UUID(row["entity_id"]),
            title=row["title"],
            error_code=row.get("error_code"),
            error_message=row.get("error_message"),
            result_summary=row.get("result_summary"),
            started_at=_parse_required_datetime(row["started_at"]),
            completed_at=_parse_datetime(row.get("completed_at")),
            created_at=_parse_required_datetime(row["created_at"]),
            updated_at=_parse_required_datetime(row["updated_at"]),
        )

    @staticmethod
    def _to_insert_row(job: Job) -> dict[str, Any]:
        return {
            "id": str(job.id),
            "organization_id": str(job.organization_id),
            "requested_by_user_id": str(job.requested_by_user_id),
            "kind": job.kind.value,
            "status": job.status.value,
            "entity_type": job.entity_type.value,
            "entity_id": str(job.entity_id),
            "title": job.title,
            "error_code": job.error_code,
            "error_message": job.error_message,
            "result_summary": job.result_summary,
            "started_at": job.started_at.isoformat(),
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }

    @staticmethod
    def _to_update_row(job: Job) -> dict[str, Any]:
        # `id`, `created_at`, `started_at`, `organization_id`,
        # `requested_by_user_id`, `kind`, `entity_type`, `title` are
        # immutable post-insert. `entity_id` is mutable (extraction
        # repoints from extraction_job.id → property.id post-completion).
        return {
            "status": job.status.value,
            "entity_id": str(job.entity_id),
            "error_code": job.error_code,
            "error_message": job.error_message,
            "result_summary": job.result_summary,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }

    async def insert(self, job: Job) -> Job:
        result = await self._client.table(self.TABLE).insert(self._to_insert_row(job)).execute()
        return self._to_domain(result.data[0])

    async def update(self, job: Job) -> Job:
        result = (
            await self._client.table(self.TABLE)
            .update(self._to_update_row(job))
            .eq("id", str(job.id))
            .execute()
        )
        if not result.data:
            raise KeyError(f"Job not found: {job.id}")
        return self._to_domain(result.data[0])

    async def get_by_id(self, job_id: UUID) -> Job | None:
        result = (
            await self._client.table(self.TABLE)
            .select("*")
            .eq("id", str(job_id))
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def list(
        self,
        *,
        organization_id: UUID,
        statuses: list[JobStatus] | None = None,
        kind: JobKind | None = None,
        entity_type: JobEntityType | None = None,
        entity_id: UUID | None = None,
        limit: int = 10,
    ) -> list[Job]:
        q = self._client.table(self.TABLE).select("*").eq("organization_id", str(organization_id))
        if statuses:
            q = q.in_("status", [s.value for s in statuses])
        if kind is not None:
            q = q.eq("kind", kind.value)
        if entity_type is not None:
            q = q.eq("entity_type", entity_type.value)
        if entity_id is not None:
            q = q.eq("entity_id", str(entity_id))
        result = await q.order("created_at", desc=True).limit(limit).execute()
        return [self._to_domain(r) for r in result.data]
