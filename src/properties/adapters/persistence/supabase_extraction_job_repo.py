from __future__ import annotations

from uuid import UUID

from supabase import AsyncClient

from properties.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from properties.domain.models.extraction_job import (
    ExtractionJob,
    ExtractionJobStatus,
)


class SupabaseExtractionJobRepository(ExtractionJobRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def _to_domain(self, row: dict) -> ExtractionJob:
        return ExtractionJob(
            id=UUID(row["id"]),
            user_id=UUID(row["user_id"]),
            organization_id=UUID(row["organization_id"]),
            status=ExtractionJobStatus(row["status"]),
            document_keys=row["document_keys"],
            listing_type=row.get("listing_type"),
            typology=row.get("typology"),
            property_id=UUID(row["property_id"]) if row.get("property_id") else None,
            error_message=row.get("error_message"),
            tracked_job_id=UUID(row["tracked_job_id"]) if row.get("tracked_job_id") else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _to_row(self, job: ExtractionJob) -> dict:
        return {
            "id": str(job.id),
            "user_id": str(job.user_id),
            "organization_id": str(job.organization_id),
            "status": job.status.value,
            "document_keys": job.document_keys,
            "listing_type": job.listing_type,
            "typology": job.typology,
            "property_id": str(job.property_id) if job.property_id else None,
            "error_message": job.error_message,
            "tracked_job_id": str(job.tracked_job_id) if job.tracked_job_id else None,
        }

    async def save(self, job: ExtractionJob) -> ExtractionJob:
        result = await self._client.table("extraction_jobs").insert(self._to_row(job)).execute()
        return self._to_domain(result.data[0])

    async def get_by_id(self, job_id: UUID) -> ExtractionJob | None:
        result = (
            await self._client.table("extraction_jobs").select("*").eq("id", str(job_id)).execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def list_by_organization(self, organization_id: UUID) -> list[ExtractionJob]:
        result = (
            await self._client.table("extraction_jobs")
            .select("*")
            .eq("organization_id", str(organization_id))
            .order("created_at", desc=True)
            .execute()
        )
        return [self._to_domain(row) for row in result.data]

    async def update(self, job: ExtractionJob) -> ExtractionJob:
        row = self._to_row(job)
        result = (
            await self._client.table("extraction_jobs").update(row).eq("id", str(job.id)).execute()
        )
        return self._to_domain(result.data[0])

    async def delete_by_property_id(self, property_id: UUID) -> None:
        pid = str(property_id)
        # Find the job IDs first so we can cascade delete document_contents
        # (FK extraction_jobs.id has no ondelete=CASCADE).
        jobs_result = (
            await self._client.table("extraction_jobs")
            .select("id")
            .eq("property_id", pid)
            .execute()
        )
        job_ids = [row["id"] for row in jobs_result.data]
        if not job_ids:
            return

        await (
            self._client.table("document_contents")
            .delete()
            .in_("extraction_job_id", job_ids)
            .execute()
        )
        await self._client.table("extraction_jobs").delete().in_("id", job_ids).execute()
