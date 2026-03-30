from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from contract_intelligence.domain.entities.generated_contract import (
    GeneratedContract,
    GeneratedContractArtifact,
)
from contract_intelligence.domain.entities.source_document import (
    SourceDocument,
    SourceExtractionRun,
    SourceFieldEvidence,
    SourceParseRun,
    SourceSection,
    SourceSectionAnalysis,
    SourceSectionAnalysisReference,
    SourceSectionAnalysisRun,
    UploadStatus,
)
from contract_intelligence.domain.entities.template import (
    ContractTemplate,
    TemplateSection,
    TemplateVersion,
)


class SourceDocumentRepository(ABC):
    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def save(self, document: SourceDocument) -> SourceDocument: ...

    @abstractmethod
    async def get_by_id(self, document_id: UUID) -> SourceDocument | None: ...

    @abstractmethod
    async def get_by_hash(self, document_hash: str) -> SourceDocument | None: ...

    @abstractmethod
    async def list_all(self) -> list[SourceDocument]: ...

    @abstractmethod
    async def update_page_count(self, document_id: UUID, page_count: int) -> None: ...

    @abstractmethod
    async def update_status(self, document_id: UUID, status: UploadStatus) -> None: ...

    @abstractmethod
    async def save_parse_run(self, parse_run: SourceParseRun) -> SourceParseRun: ...

    @abstractmethod
    async def save_extraction_run(
        self, extraction_run: SourceExtractionRun
    ) -> SourceExtractionRun: ...

    @abstractmethod
    async def get_field_evidence_by_document_id(
        self, document_id: UUID
    ) -> list[SourceFieldEvidence]: ...

    @abstractmethod
    async def get_field_evidence_by_id(self, evidence_id: UUID) -> SourceFieldEvidence | None: ...

    @abstractmethod
    async def update_field_evidence(self, evidence: SourceFieldEvidence) -> None: ...

    @abstractmethod
    async def save_field_evidence(self, evidence: SourceFieldEvidence) -> SourceFieldEvidence: ...

    @abstractmethod
    async def update_parse_run(self, parse_run: SourceParseRun) -> None: ...

    @abstractmethod
    async def update_extraction_run(self, extraction_run: SourceExtractionRun) -> None: ...

    @abstractmethod
    async def save_analysis_run(
        self, run: SourceSectionAnalysisRun
    ) -> SourceSectionAnalysisRun: ...

    @abstractmethod
    async def update_analysis_run(self, run: SourceSectionAnalysisRun) -> None: ...


class SourceSectionRepository(ABC):
    # --- sections ---
    @abstractmethod
    async def get_sections_by_document_id(self, document_id: UUID) -> list[SourceSection]: ...

    @abstractmethod
    async def get_section_by_id(self, section_id: UUID) -> SourceSection | None: ...

    @abstractmethod
    async def update_section(self, section: SourceSection) -> None: ...

    @abstractmethod
    async def save_section(self, section: SourceSection) -> SourceSection: ...

    # --- analysis ---
    @abstractmethod
    async def save_analysis(self, analysis: SourceSectionAnalysis) -> SourceSectionAnalysis: ...

    @abstractmethod
    async def get_analysis_by_id(self, analysis_id: UUID) -> SourceSectionAnalysis | None: ...

    @abstractmethod
    async def get_analyses_by_run_id(self, run_id: UUID) -> list[SourceSectionAnalysis]: ...

    @abstractmethod
    async def update_analysis(self, analysis: SourceSectionAnalysis) -> None: ...

    # --- references ---
    @abstractmethod
    async def save_analysis_reference(
        self, ref: SourceSectionAnalysisReference
    ) -> SourceSectionAnalysisReference: ...


class TemplateRepository(ABC):
    @abstractmethod
    async def save_template(self, template: ContractTemplate) -> ContractTemplate: ...

    @abstractmethod
    async def get_template_by_id(self, template_id: UUID) -> ContractTemplate | None: ...

    @abstractmethod
    async def save_version(self, version: TemplateVersion) -> TemplateVersion: ...

    @abstractmethod
    async def get_version_by_id(self, version_id: UUID) -> TemplateVersion | None: ...

    @abstractmethod
    async def get_section_by_id(self, section_id: UUID) -> TemplateSection | None: ...

    @abstractmethod
    async def update_version(self, version: TemplateVersion) -> None: ...

    @abstractmethod
    async def update_section(self, section: TemplateSection) -> None: ...

    @abstractmethod
    async def update_template_current_version(
        self, template_id: UUID, version_id: UUID
    ) -> None: ...


class GeneratedContractRepository(ABC):
    @abstractmethod
    async def save(self, contract: GeneratedContract) -> GeneratedContract: ...

    @abstractmethod
    async def get_by_id(self, contract_id: UUID) -> GeneratedContract | None: ...

    @abstractmethod
    async def update(self, contract: GeneratedContract) -> None: ...

    @abstractmethod
    async def save_artifact(
        self, artifact: GeneratedContractArtifact
    ) -> GeneratedContractArtifact: ...
