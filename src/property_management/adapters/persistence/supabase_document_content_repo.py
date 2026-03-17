from __future__ import annotations

from uuid import UUID

from supabase import AsyncClient

from property_management.application.ports.repositories.document_content_repository import (
    DocumentContentRepository,
)
from property_management.domain.models.document_content import DocumentContent


class SupabaseDocumentContentRepository(DocumentContentRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def _to_domain(self, row: dict) -> DocumentContent:
        return DocumentContent(
            id=UUID(row["id"]),
            extraction_job_id=UUID(row["extraction_job_id"]),
            document_index=row["document_index"],
            document_key=row["document_key"],
            parsed_text=row["parsed_text"],
            category=row.get("category"),
            document_subtype=row.get("document_subtype"),
            extraction_reasoning=row.get("extraction_reasoning"),
            created_at=row["created_at"],
        )

    def _to_row(self, content: DocumentContent) -> dict:
        return {
            "id": str(content.id),
            "extraction_job_id": str(content.extraction_job_id),
            "document_index": content.document_index,
            "document_key": content.document_key,
            "parsed_text": content.parsed_text,
            "category": content.category,
            "document_subtype": content.document_subtype,
            "extraction_reasoning": content.extraction_reasoning,
        }

    async def save(self, content: DocumentContent) -> DocumentContent:
        result = (
            await self._client.table("document_contents").insert(self._to_row(content)).execute()
        )
        return self._to_domain(result.data[0])

    async def save_batch(self, contents: list[DocumentContent]) -> list[DocumentContent]:
        rows = [self._to_row(c) for c in contents]
        result = await self._client.table("document_contents").insert(rows).execute()
        return [self._to_domain(row) for row in result.data]

    async def get_by_job_id(self, job_id: UUID) -> list[DocumentContent]:
        result = (
            await self._client.table("document_contents")
            .select("*")
            .eq("extraction_job_id", str(job_id))
            .order("document_index")
            .execute()
        )
        return [self._to_domain(row) for row in result.data]

    async def update_classification(
        self, content_id: UUID, category: str, document_subtype: str
    ) -> None:
        await (
            self._client.table("document_contents")
            .update({"category": category, "document_subtype": document_subtype})
            .eq("id", str(content_id))
            .execute()
        )

    async def update_extraction_reasoning(
        self, content_id: UUID, extraction_reasoning: str
    ) -> None:
        await (
            self._client.table("document_contents")
            .update({"extraction_reasoning": extraction_reasoning})
            .eq("id", str(content_id))
            .execute()
        )
