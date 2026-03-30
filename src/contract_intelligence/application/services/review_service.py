from __future__ import annotations

import uuid

from contract_intelligence.application.dtos.review import (
    SourceReviewBundleRead,
    UpdateFieldEvidenceReviewRequest,
    UpdateSourceSectionReviewRequest,
)
from contract_intelligence.application.ports.repositories import SourceDocumentRepository


class ReviewService:
    def __init__(self, repo: SourceDocumentRepository) -> None:
        self._repo = repo

    async def get_source_review_bundle(
        self, source_document_id: uuid.UUID
    ) -> SourceReviewBundleRead:
        raise NotImplementedError

    async def update_source_section_review(
        self, section_id: uuid.UUID, payload: UpdateSourceSectionReviewRequest
    ) -> None:
        raise NotImplementedError

    async def update_field_evidence_review(
        self, evidence_id: uuid.UUID, payload: UpdateFieldEvidenceReviewRequest
    ) -> None:
        raise NotImplementedError
