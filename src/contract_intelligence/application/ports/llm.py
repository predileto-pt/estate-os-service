from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from contract_intelligence.application.dtos.section_analysis import (
        SourceSectionAnalysisBatchOutput,
    )
    from contract_intelligence.domain.entities.source_document import (
        SourceFieldEvidence,
        SourceSection,
    )


class SectionAnalysisLLMPort(ABC):
    @abstractmethod
    async def analyze_sections(
        self,
        sections: list[SourceSection],
        field_evidence: list[SourceFieldEvidence],
        *,
        document_id: UUID | None = None,
    ) -> SourceSectionAnalysisBatchOutput: ...
