from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from contract_intelligence.application.dtos.section_analysis import (
        SourceSectionAnalysisBatchOutput,
    )
    from contract_intelligence.domain.entities.source_document import (
        SourceFieldEvidence,
        SourceSection,
    )


class SectionAnalysisLLMPort(Protocol):
    async def analyze_sections(
        self,
        sections: list[SourceSection],
        field_evidence: list[SourceFieldEvidence],
        *,
        document_id: UUID | None = None,
    ) -> SourceSectionAnalysisBatchOutput: ...
