from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog

from contract_intelligence.application.dtos.section_analysis import SectionAnalysisOutput
from contract_intelligence.application.ports.llm import SectionAnalysisLLMPort
from contract_intelligence.application.ports.repositories import (
    SourceDocumentRepository,
    SourceSectionRepository,
)
from contract_intelligence.domain.entities.source_document import (
    RunStatus,
    SourceSectionAnalysis,
    SourceSectionAnalysisReference,
    SourceSectionAnalysisRun,
    UploadStatus,
)
from contract_intelligence.domain.exceptions import DomainError, SourceDocumentNotFoundError

logger = structlog.get_logger()


class SectionAnalysisError(DomainError):
    pass


class SectionAnalysisService:
    def __init__(
        self,
        doc_repo: SourceDocumentRepository,
        section_repo: SourceSectionRepository,
        llm: SectionAnalysisLLMPort,
    ) -> None:
        self._doc_repo = doc_repo
        self._section_repo = section_repo
        self._llm = llm

    async def analyze(self, document_id: UUID) -> SourceSectionAnalysisRun:
        # 1. Fetch document
        document = await self._doc_repo.get_by_id(document_id)
        if not document:
            raise SourceDocumentNotFoundError(document_id)

        # 2. Guard: upload_status must be EXTRACTED
        if document.upload_status != UploadStatus.EXTRACTED:
            raise SectionAnalysisError(
                f"Document {document_id} has status {document.upload_status}, expected EXTRACTED"
            )

        # 3. Idempotency guard: skip if a succeeded analysis run already exists
        succeeded_runs = [r for r in document.analysis_runs if r.status == RunStatus.SUCCEEDED]
        if succeeded_runs:
            logger.info(
                "analysis_skipped_already_completed",
                document_id=str(document_id),
                existing_run_id=str(succeeded_runs[0].id),
            )
            return succeeded_runs[0]

        # 4. Guard: document must have sections
        if not document.sections:
            raise SectionAnalysisError(f"Document {document_id} has no sections to analyze")

        # 5. Create analysis run
        run = SourceSectionAnalysisRun(source_document_id=document.id)
        run.mark_running()
        run = await self._doc_repo.save_analysis_run(run)

        try:
            # 6a. Fetch field evidence
            field_evidence = await self._doc_repo.get_field_evidence_by_document_id(document.id)

            # 6b. Call LLM
            llm_output = await self._llm.analyze_sections(
                document.sections, field_evidence, document_id=document.id
            )

            # 6c. Map section IDs for validation
            section_ids = {s.id for s in document.sections}

            # 6d. Persist each analysis and its references
            processed_count = 0
            skipped_count = 0
            for analysis_output in llm_output.analyses:
                if analysis_output.source_section_id not in section_ids:
                    skipped_count += 1
                    logger.warning(
                        "llm_returned_unknown_section_id",
                        section_id=str(analysis_output.source_section_id),
                        document_id=str(document_id),
                    )
                    continue

                analysis = self._build_analysis(run.id, analysis_output)
                analysis = await self._section_repo.save_analysis(analysis)
                processed_count += 1

                for ref_output in analysis_output.references:
                    ref = SourceSectionAnalysisReference(
                        source_section_analysis_id=analysis.id,
                        reference_type=ref_output.reference_type,
                        reference_key=ref_output.reference_key,
                        display_label=ref_output.display_label,
                        confidence=ref_output.confidence,
                    )
                    await self._section_repo.save_analysis_reference(ref)

            logger.info(
                "analysis_results",
                document_id=str(document_id),
                processed_count=processed_count,
                skipped_count=skipped_count,
                total_sections=len(document.sections),
            )

            # Fail the run if no analyses were produced
            if processed_count == 0:
                raise SectionAnalysisError(
                    f"LLM returned 0 valid analyses for document {document_id} "
                    f"(skipped={skipped_count}, sections={len(document.sections)})"
                )

            # 7. Mark run succeeded and document as analyzed
            run.mark_succeeded(completed_at=datetime.now(UTC))
            await self._doc_repo.update_analysis_run(run)

            document.mark_analyzed()
            await self._doc_repo.update_status(document.id, document.upload_status)

        except Exception:
            run.mark_failed(completed_at=datetime.now(UTC))
            await self._doc_repo.update_analysis_run(run)
            raise

        return run

    @staticmethod
    def _build_analysis(run_id: UUID, output: SectionAnalysisOutput) -> SourceSectionAnalysis:
        return SourceSectionAnalysis(
            source_section_analysis_run_id=run_id,
            source_section_id=output.source_section_id,
            section_type=output.section_type,
            reasoning=output.reasoning,
            risk_level=output.risk_level,
            recommended_strategy=output.recommended_strategy,
        )
