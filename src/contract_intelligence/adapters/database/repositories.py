from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from contract_intelligence.adapters.database import models as orm
from contract_intelligence.domain.entities.generated_contract import (
    GeneratedContract,
    GeneratedContractArtifact,
    GeneratedContractParty,
    GeneratedContractSection,
    GeneratedContractStatus,
)
from contract_intelligence.domain.entities.source_document import (
    AnalysisReferenceType,
    RecommendedStrategy,
    ReviewStatus,
    RiskLevel,
    RunStatus,
    SectionType,
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
    SectionStatus,
    TemplateCondition,
    TemplateFieldBinding,
    TemplatePartySlot,
    TemplateSection,
    TemplateStatus,
    TemplateVersion,
)


# ---------------------------------------------------------------------------
# Source Document Repository
# ---------------------------------------------------------------------------


class SqlAlchemySourceDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _field_evidence_to_domain(m: orm.SourceFieldEvidenceModel) -> SourceFieldEvidence:
        return SourceFieldEvidence(
            id=m.id,
            source_extraction_run_id=m.source_extraction_run_id,
            source_section_id=m.source_section_id,
            field_key=m.field_key,
            field_value_json=m.field_value_json,
            source_text=m.source_text,
            page_number=m.page_number,
            confidence=m.confidence,
            review_status=ReviewStatus(m.review_status),
            corrected_value_json=m.corrected_value_json,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _section_to_domain(m: orm.SourceSectionModel) -> SourceSection:
        return SourceSection(
            id=m.id,
            source_document_id=m.source_document_id,
            section_key=m.section_key,
            title=m.title,
            page_start=m.page_start,
            page_end=m.page_end,
            sort_order=m.sort_order,
            extracted_text=m.extracted_text,
            normalized_text=m.normalized_text,
            classification_confidence=m.classification_confidence,
            review_status=ReviewStatus(m.review_status),
            created_at=m.created_at,
            updated_at=m.updated_at,
            field_evidence=[
                SqlAlchemySourceDocumentRepository._field_evidence_to_domain(fe)
                for fe in m.field_evidence
            ],
        )

    @staticmethod
    def _parse_run_to_domain(m: orm.SourceParseRunModel) -> SourceParseRun:
        return SourceParseRun(
            id=m.id,
            source_document_id=m.source_document_id,
            provider=m.provider,
            provider_job_id=m.provider_job_id,
            parse_config_json=m.parse_config_json,
            response_json=m.response_json,
            status=RunStatus(m.status),
            created_at=m.created_at,
            completed_at=m.completed_at,
        )

    @staticmethod
    def _extraction_run_to_domain(m: orm.SourceExtractionRunModel) -> SourceExtractionRun:
        return SourceExtractionRun(
            id=m.id,
            source_document_id=m.source_document_id,
            provider=m.provider,
            provider_job_id=m.provider_job_id,
            schema_version=m.schema_version,
            extraction_schema_json=m.extraction_schema_json,
            result_json=m.result_json,
            status=RunStatus(m.status),
            created_at=m.created_at,
            completed_at=m.completed_at,
            field_evidence=[
                SqlAlchemySourceDocumentRepository._field_evidence_to_domain(fe)
                for fe in m.field_evidence
            ],
        )

    @staticmethod
    def _analysis_run_to_domain(m: orm.SourceSectionAnalysisRunModel) -> SourceSectionAnalysisRun:
        return SourceSectionAnalysisRun(
            id=m.id,
            source_document_id=m.source_document_id,
            provider=m.provider,
            model_name=m.model_name,
            prompt_version=m.prompt_version,
            status=RunStatus(m.status),
            created_at=m.created_at,
            completed_at=m.completed_at,
        )

    @staticmethod
    def _to_domain(m: orm.ContractSourceDocumentModel) -> SourceDocument:
        return SourceDocument(
            id=m.id,
            organization_id=m.organization_id,
            filename=m.filename,
            storage_url=m.storage_url,
            mime_type=m.mime_type,
            page_count=m.page_count,
            language_code=m.language_code,
            document_hash=m.document_hash,
            upload_status=UploadStatus(m.upload_status),
            created_at=m.created_at,
            parse_runs=[
                SqlAlchemySourceDocumentRepository._parse_run_to_domain(pr) for pr in m.parse_runs
            ],
            sections=[SqlAlchemySourceDocumentRepository._section_to_domain(s) for s in m.sections],
            extraction_runs=[
                SqlAlchemySourceDocumentRepository._extraction_run_to_domain(er)
                for er in m.extraction_runs
            ],
            analysis_runs=[
                SqlAlchemySourceDocumentRepository._analysis_run_to_domain(ar)
                for ar in m.analysis_runs
            ],
        )

    # -- repository methods --------------------------------------------------

    async def save(self, document: SourceDocument) -> SourceDocument:
        row = orm.ContractSourceDocumentModel(
            id=document.id,
            organization_id=document.organization_id,
            filename=document.filename,
            storage_url=document.storage_url,
            mime_type=document.mime_type,
            page_count=document.page_count,
            language_code=document.language_code,
            document_hash=document.document_hash,
            upload_status=document.upload_status.value,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        document.created_at = row.created_at
        return document

    async def get_by_id(self, document_id: UUID) -> SourceDocument | None:
        stmt = (
            select(orm.ContractSourceDocumentModel)
            .where(orm.ContractSourceDocumentModel.id == document_id)
            .options(
                selectinload(orm.ContractSourceDocumentModel.parse_runs),
                selectinload(orm.ContractSourceDocumentModel.sections).selectinload(
                    orm.SourceSectionModel.field_evidence
                ),
                selectinload(orm.ContractSourceDocumentModel.extraction_runs).selectinload(
                    orm.SourceExtractionRunModel.field_evidence
                ),
                selectinload(orm.ContractSourceDocumentModel.analysis_runs),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_hash(self, document_hash: str) -> SourceDocument | None:
        stmt = (
            select(orm.ContractSourceDocumentModel)
            .where(orm.ContractSourceDocumentModel.document_hash == document_hash)
            .options(
                selectinload(orm.ContractSourceDocumentModel.parse_runs),
                selectinload(orm.ContractSourceDocumentModel.sections).selectinload(
                    orm.SourceSectionModel.field_evidence
                ),
                selectinload(orm.ContractSourceDocumentModel.extraction_runs).selectinload(
                    orm.SourceExtractionRunModel.field_evidence
                ),
                selectinload(orm.ContractSourceDocumentModel.analysis_runs),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_all(self) -> list[SourceDocument]:
        stmt = (
            select(orm.ContractSourceDocumentModel)
            .options(
                selectinload(orm.ContractSourceDocumentModel.parse_runs),
                selectinload(orm.ContractSourceDocumentModel.sections).selectinload(
                    orm.SourceSectionModel.field_evidence
                ),
                selectinload(orm.ContractSourceDocumentModel.extraction_runs).selectinload(
                    orm.SourceExtractionRunModel.field_evidence
                ),
                selectinload(orm.ContractSourceDocumentModel.analysis_runs),
            )
            .order_by(orm.ContractSourceDocumentModel.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_domain(r) for r in rows]

    async def list_by_organization(self, organization_id: UUID) -> list[SourceDocument]:
        stmt = (
            select(orm.ContractSourceDocumentModel)
            .where(orm.ContractSourceDocumentModel.organization_id == str(organization_id))
            .options(
                selectinload(orm.ContractSourceDocumentModel.parse_runs),
                selectinload(orm.ContractSourceDocumentModel.sections).selectinload(
                    orm.SourceSectionModel.field_evidence
                ),
                selectinload(orm.ContractSourceDocumentModel.extraction_runs).selectinload(
                    orm.SourceExtractionRunModel.field_evidence
                ),
                selectinload(orm.ContractSourceDocumentModel.analysis_runs),
            )
            .order_by(orm.ContractSourceDocumentModel.created_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._to_domain(r) for r in rows]

    async def update_page_count(self, document_id: UUID, page_count: int) -> None:
        row = await self._session.get(orm.ContractSourceDocumentModel, document_id)
        if row:
            row.page_count = page_count
            await self._session.flush()

    async def update_status(self, document_id: UUID, status: UploadStatus) -> None:
        row = await self._session.get(orm.ContractSourceDocumentModel, document_id)
        if row:
            row.upload_status = status.value
            await self._session.flush()

    async def save_parse_run(self, parse_run: SourceParseRun) -> SourceParseRun:
        row = orm.SourceParseRunModel(
            id=parse_run.id,
            source_document_id=parse_run.source_document_id,
            provider=parse_run.provider,
            provider_job_id=parse_run.provider_job_id,
            parse_config_json=parse_run.parse_config_json,
            response_json=parse_run.response_json,
            status=parse_run.status.value,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        parse_run.created_at = row.created_at
        return parse_run

    async def save_extraction_run(self, extraction_run: SourceExtractionRun) -> SourceExtractionRun:
        row = orm.SourceExtractionRunModel(
            id=extraction_run.id,
            source_document_id=extraction_run.source_document_id,
            provider=extraction_run.provider,
            provider_job_id=extraction_run.provider_job_id,
            schema_version=extraction_run.schema_version,
            extraction_schema_json=extraction_run.extraction_schema_json,
            result_json=extraction_run.result_json,
            status=extraction_run.status.value,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        extraction_run.created_at = row.created_at
        return extraction_run

    async def get_field_evidence_by_document_id(
        self, document_id: UUID
    ) -> list[SourceFieldEvidence]:
        stmt = (
            select(orm.SourceFieldEvidenceModel)
            .join(orm.SourceExtractionRunModel)
            .where(orm.SourceExtractionRunModel.source_document_id == document_id)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._field_evidence_to_domain(r) for r in rows]

    async def get_field_evidence_by_id(self, evidence_id: UUID) -> SourceFieldEvidence | None:
        row = await self._session.get(orm.SourceFieldEvidenceModel, evidence_id)
        return self._field_evidence_to_domain(row) if row else None

    async def update_field_evidence(self, evidence: SourceFieldEvidence) -> None:
        row = await self._session.get(orm.SourceFieldEvidenceModel, evidence.id)
        if row:
            row.review_status = evidence.review_status.value
            row.corrected_value_json = evidence.corrected_value_json
            await self._session.flush()

    async def save_field_evidence(self, evidence: SourceFieldEvidence) -> SourceFieldEvidence:
        row = orm.SourceFieldEvidenceModel(
            id=evidence.id,
            source_extraction_run_id=evidence.source_extraction_run_id,
            source_section_id=evidence.source_section_id,
            field_key=evidence.field_key,
            field_value_json=evidence.field_value_json,
            source_text=evidence.source_text,
            page_number=evidence.page_number,
            confidence=evidence.confidence,
            review_status=evidence.review_status.value,
            corrected_value_json=evidence.corrected_value_json,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        evidence.created_at = row.created_at
        evidence.updated_at = row.updated_at
        return evidence

    async def update_parse_run(self, parse_run: SourceParseRun) -> None:
        row = await self._session.get(orm.SourceParseRunModel, parse_run.id)
        if row:
            row.provider_job_id = parse_run.provider_job_id
            row.response_json = parse_run.response_json
            row.status = parse_run.status.value
            row.completed_at = parse_run.completed_at
            await self._session.flush()

    async def update_extraction_run(self, extraction_run: SourceExtractionRun) -> None:
        row = await self._session.get(orm.SourceExtractionRunModel, extraction_run.id)
        if row:
            row.provider_job_id = extraction_run.provider_job_id
            row.result_json = extraction_run.result_json
            row.status = extraction_run.status.value
            row.completed_at = extraction_run.completed_at
            await self._session.flush()

    async def save_analysis_run(self, run: SourceSectionAnalysisRun) -> SourceSectionAnalysisRun:
        row = orm.SourceSectionAnalysisRunModel(
            id=run.id,
            source_document_id=run.source_document_id,
            provider=run.provider,
            model_name=run.model_name,
            prompt_version=run.prompt_version,
            status=run.status.value,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        run.created_at = row.created_at
        return run

    async def update_analysis_run(self, run: SourceSectionAnalysisRun) -> None:
        row = await self._session.get(orm.SourceSectionAnalysisRunModel, run.id)
        if row:
            row.status = run.status.value
            row.completed_at = run.completed_at
            await self._session.flush()


# ---------------------------------------------------------------------------
# Source Section Repository
# ---------------------------------------------------------------------------


class SqlAlchemySourceSectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _field_evidence_to_domain(m: orm.SourceFieldEvidenceModel) -> SourceFieldEvidence:
        return SqlAlchemySourceDocumentRepository._field_evidence_to_domain(m)

    @staticmethod
    def _section_to_domain(m: orm.SourceSectionModel) -> SourceSection:
        return SqlAlchemySourceDocumentRepository._section_to_domain(m)

    @staticmethod
    def _analysis_reference_to_domain(
        m: orm.SourceSectionAnalysisReferenceModel,
    ) -> SourceSectionAnalysisReference:
        return SourceSectionAnalysisReference(
            id=m.id,
            source_section_analysis_id=m.source_section_analysis_id,
            reference_type=AnalysisReferenceType(m.reference_type),
            reference_key=m.reference_key,
            display_label=m.display_label,
            confidence=m.confidence,
            created_at=m.created_at,
        )

    @staticmethod
    def _analysis_to_domain(m: orm.SourceSectionAnalysisModel) -> SourceSectionAnalysis:
        return SourceSectionAnalysis(
            id=m.id,
            source_section_analysis_run_id=m.source_section_analysis_run_id,
            source_section_id=m.source_section_id,
            section_type=SectionType(m.section_type),
            reasoning=m.reasoning,
            risk_level=RiskLevel(m.risk_level),
            recommended_strategy=RecommendedStrategy(m.recommended_strategy),
            review_status=ReviewStatus(m.review_status),
            review_notes=m.review_notes,
            corrected_section_type=SectionType(m.corrected_section_type)
            if m.corrected_section_type
            else None,
            corrected_risk_level=RiskLevel(m.corrected_risk_level)
            if m.corrected_risk_level
            else None,
            corrected_strategy=RecommendedStrategy(m.corrected_strategy)
            if m.corrected_strategy
            else None,
            created_at=m.created_at,
            updated_at=m.updated_at,
            references=[
                SqlAlchemySourceSectionRepository._analysis_reference_to_domain(r)
                for r in m.references
            ],
        )

    # -- section methods -----------------------------------------------------

    async def get_sections_by_document_id(self, document_id: UUID) -> list[SourceSection]:
        stmt = (
            select(orm.SourceSectionModel)
            .where(orm.SourceSectionModel.source_document_id == document_id)
            .options(selectinload(orm.SourceSectionModel.field_evidence))
            .order_by(orm.SourceSectionModel.sort_order)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._section_to_domain(r) for r in rows]

    async def get_section_by_id(self, section_id: UUID) -> SourceSection | None:
        stmt = (
            select(orm.SourceSectionModel)
            .where(orm.SourceSectionModel.id == section_id)
            .options(selectinload(orm.SourceSectionModel.field_evidence))
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._section_to_domain(row) if row else None

    async def update_section(self, section: SourceSection) -> None:
        row = await self._session.get(orm.SourceSectionModel, section.id)
        if row:
            row.section_key = section.section_key
            row.title = section.title
            row.extracted_text = section.extracted_text
            row.normalized_text = section.normalized_text
            row.classification_confidence = section.classification_confidence
            row.review_status = section.review_status.value
            await self._session.flush()

    async def save_section(self, section: SourceSection) -> SourceSection:
        row = orm.SourceSectionModel(
            id=section.id,
            source_document_id=section.source_document_id,
            section_key=section.section_key,
            title=section.title,
            page_start=section.page_start,
            page_end=section.page_end,
            sort_order=section.sort_order,
            extracted_text=section.extracted_text,
            normalized_text=section.normalized_text,
            classification_confidence=section.classification_confidence,
            review_status=section.review_status.value,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        section.created_at = row.created_at
        section.updated_at = row.updated_at
        return section

    # -- analysis methods ----------------------------------------------------

    async def save_analysis(self, analysis: SourceSectionAnalysis) -> SourceSectionAnalysis:
        row = orm.SourceSectionAnalysisModel(
            id=analysis.id,
            source_section_analysis_run_id=analysis.source_section_analysis_run_id,
            source_section_id=analysis.source_section_id,
            section_type=analysis.section_type.value,
            reasoning=analysis.reasoning,
            risk_level=analysis.risk_level.value,
            recommended_strategy=analysis.recommended_strategy.value,
            review_status=analysis.review_status.value,
            review_notes=analysis.review_notes,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        analysis.created_at = row.created_at
        analysis.updated_at = row.updated_at
        return analysis

    async def get_analysis_by_id(self, analysis_id: UUID) -> SourceSectionAnalysis | None:
        stmt = (
            select(orm.SourceSectionAnalysisModel)
            .where(orm.SourceSectionAnalysisModel.id == analysis_id)
            .options(selectinload(orm.SourceSectionAnalysisModel.references))
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._analysis_to_domain(row) if row else None

    async def get_analyses_by_run_id(self, run_id: UUID) -> list[SourceSectionAnalysis]:
        stmt = (
            select(orm.SourceSectionAnalysisModel)
            .where(orm.SourceSectionAnalysisModel.source_section_analysis_run_id == run_id)
            .options(selectinload(orm.SourceSectionAnalysisModel.references))
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [self._analysis_to_domain(r) for r in rows]

    async def update_analysis(self, analysis: SourceSectionAnalysis) -> None:
        row = await self._session.get(orm.SourceSectionAnalysisModel, analysis.id)
        if row:
            row.review_status = analysis.review_status.value
            row.review_notes = analysis.review_notes
            row.corrected_section_type = (
                analysis.corrected_section_type.value if analysis.corrected_section_type else None
            )
            row.corrected_risk_level = (
                analysis.corrected_risk_level.value if analysis.corrected_risk_level else None
            )
            row.corrected_strategy = (
                analysis.corrected_strategy.value if analysis.corrected_strategy else None
            )
            await self._session.flush()

    # -- reference methods ---------------------------------------------------

    async def save_analysis_reference(
        self, ref: SourceSectionAnalysisReference
    ) -> SourceSectionAnalysisReference:
        row = orm.SourceSectionAnalysisReferenceModel(
            id=ref.id,
            source_section_analysis_id=ref.source_section_analysis_id,
            reference_type=ref.reference_type.value,
            reference_key=ref.reference_key,
            display_label=ref.display_label,
            confidence=ref.confidence,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        ref.created_at = row.created_at
        return ref


# ---------------------------------------------------------------------------
# Template Repository
# ---------------------------------------------------------------------------


class SqlAlchemyTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _section_to_domain(m: orm.TemplateSectionModel) -> TemplateSection:
        return TemplateSection(
            id=m.id,
            template_version_id=m.template_version_id,
            section_key=m.section_key,
            title=m.title,
            section_type=m.section_type,
            sort_order=m.sort_order,
            is_repeatable=m.is_repeatable,
            is_optional=m.is_optional,
            condition_expression=m.condition_expression,
            render_template=m.render_template,
            source_text_snapshot=m.source_text_snapshot,
            status=SectionStatus(m.status),
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _field_binding_to_domain(m: orm.TemplateFieldBindingModel) -> TemplateFieldBinding:
        return TemplateFieldBinding(
            id=m.id,
            template_version_id=m.template_version_id,
            template_section_id=m.template_section_id,
            field_key=m.field_key,
            binding_type=m.binding_type,
            required=m.required,
            placeholder_label=m.placeholder_label,
            description=m.description,
            default_value_json=m.default_value_json,
            validation_rules_json=m.validation_rules_json,
            source_hint=m.source_hint,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _condition_to_domain(m: orm.TemplateConditionModel) -> TemplateCondition:
        return TemplateCondition(
            id=m.id,
            template_version_id=m.template_version_id,
            template_section_id=m.template_section_id,
            condition_key=m.condition_key,
            expression=m.expression,
            description=m.description,
            created_at=m.created_at,
        )

    @staticmethod
    def _party_slot_to_domain(m: orm.TemplatePartySlotModel) -> TemplatePartySlot:
        return TemplatePartySlot(
            id=m.id,
            template_version_id=m.template_version_id,
            role_key=m.role_key,
            min_count=m.min_count,
            max_count=m.max_count,
            display_label_singular=m.display_label_singular,
            display_label_plural=m.display_label_plural,
            alias_singular=m.alias_singular,
            alias_plural=m.alias_plural,
            section_intro_label=m.section_intro_label,
            sort_order=m.sort_order,
            is_required=m.is_required,
            created_at=m.created_at,
        )

    @staticmethod
    def _version_to_domain(m: orm.ContractTemplateVersionModel) -> TemplateVersion:
        return TemplateVersion(
            id=m.id,
            contract_template_id=m.contract_template_id,
            source_document_id=m.source_document_id,
            version_number=m.version_number,
            render_engine=m.render_engine,
            schema_json=m.schema_json,
            computed_rules_json=m.computed_rules_json,
            status=TemplateStatus(m.status),
            review_notes=m.review_notes,
            created_by=m.created_by,
            approved_by=m.approved_by,
            created_at=m.created_at,
            approved_at=m.approved_at,
            sections=[SqlAlchemyTemplateRepository._section_to_domain(s) for s in m.sections],
            field_bindings=[
                SqlAlchemyTemplateRepository._field_binding_to_domain(fb) for fb in m.field_bindings
            ],
            conditions=[SqlAlchemyTemplateRepository._condition_to_domain(c) for c in m.conditions],
            party_slots=[
                SqlAlchemyTemplateRepository._party_slot_to_domain(ps) for ps in m.party_slots
            ],
        )

    @staticmethod
    def _to_domain(m: orm.ContractTemplateModel) -> ContractTemplate:
        return ContractTemplate(
            id=m.id,
            key=m.key,
            name=m.name,
            contract_type=m.contract_type,
            jurisdiction=m.jurisdiction,
            language_code=m.language_code,
            status=TemplateStatus(m.status),
            current_version_id=m.current_version_id,
            created_at=m.created_at,
            updated_at=m.updated_at,
            versions=[SqlAlchemyTemplateRepository._version_to_domain(v) for v in m.versions],
        )

    # -- repository methods --------------------------------------------------

    async def save_template(self, template: ContractTemplate) -> ContractTemplate:
        row = orm.ContractTemplateModel(
            id=template.id,
            key=template.key,
            name=template.name,
            contract_type=template.contract_type,
            jurisdiction=template.jurisdiction,
            language_code=template.language_code,
            status=template.status.value,
            current_version_id=template.current_version_id,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        template.created_at = row.created_at
        template.updated_at = row.updated_at
        return template

    async def get_template_by_id(self, template_id: UUID) -> ContractTemplate | None:
        stmt = (
            select(orm.ContractTemplateModel)
            .where(orm.ContractTemplateModel.id == template_id)
            .options(
                selectinload(orm.ContractTemplateModel.versions).selectinload(
                    orm.ContractTemplateVersionModel.sections
                ),
                selectinload(orm.ContractTemplateModel.versions).selectinload(
                    orm.ContractTemplateVersionModel.field_bindings
                ),
                selectinload(orm.ContractTemplateModel.versions).selectinload(
                    orm.ContractTemplateVersionModel.conditions
                ),
                selectinload(orm.ContractTemplateModel.versions).selectinload(
                    orm.ContractTemplateVersionModel.party_slots
                ),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def save_version(self, version: TemplateVersion) -> TemplateVersion:
        row = orm.ContractTemplateVersionModel(
            id=version.id,
            contract_template_id=version.contract_template_id,
            source_document_id=version.source_document_id,
            version_number=version.version_number,
            render_engine=version.render_engine,
            schema_json=version.schema_json,
            computed_rules_json=version.computed_rules_json,
            status=version.status.value,
            review_notes=version.review_notes,
            created_by=version.created_by,
            approved_by=version.approved_by,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        version.created_at = row.created_at
        return version

    async def get_version_by_id(self, version_id: UUID) -> TemplateVersion | None:
        stmt = (
            select(orm.ContractTemplateVersionModel)
            .where(orm.ContractTemplateVersionModel.id == version_id)
            .options(
                selectinload(orm.ContractTemplateVersionModel.sections),
                selectinload(orm.ContractTemplateVersionModel.field_bindings),
                selectinload(orm.ContractTemplateVersionModel.conditions),
                selectinload(orm.ContractTemplateVersionModel.party_slots),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._version_to_domain(row) if row else None

    async def get_section_by_id(self, section_id: UUID) -> TemplateSection | None:
        row = await self._session.get(orm.TemplateSectionModel, section_id)
        return self._section_to_domain(row) if row else None

    async def update_version(self, version: TemplateVersion) -> None:
        row = await self._session.get(orm.ContractTemplateVersionModel, version.id)
        if row:
            row.status = version.status.value
            row.review_notes = version.review_notes
            row.approved_by = version.approved_by
            row.approved_at = version.approved_at
            await self._session.flush()

    async def update_section(self, section: TemplateSection) -> None:
        row = await self._session.get(orm.TemplateSectionModel, section.id)
        if row:
            row.render_template = section.render_template
            row.status = section.status.value
            row.source_text_snapshot = section.source_text_snapshot
            await self._session.flush()

    async def update_template_current_version(self, template_id: UUID, version_id: UUID) -> None:
        row = await self._session.get(orm.ContractTemplateModel, template_id)
        if row:
            row.current_version_id = version_id
            await self._session.flush()


# ---------------------------------------------------------------------------
# Generated Contract Repository
# ---------------------------------------------------------------------------


class SqlAlchemyGeneratedContractRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- mapping helpers -----------------------------------------------------

    @staticmethod
    def _party_to_domain(m: orm.GeneratedContractPartyModel) -> GeneratedContractParty:
        return GeneratedContractParty(
            id=m.id,
            generated_contract_id=m.generated_contract_id,
            role_key=m.role_key,
            party_order=m.party_order,
            party_type=m.party_type,
            full_name=m.full_name,
            tax_id=m.tax_id,
            document_type=m.document_type,
            document_number=m.document_number,
            document_expiry=m.document_expiry,
            address_line_1=m.address_line_1,
            address_line_2=m.address_line_2,
            postal_code=m.postal_code,
            city=m.city,
            country_code=m.country_code,
            source_ref=m.source_ref,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _section_to_domain(m: orm.GeneratedContractSectionModel) -> GeneratedContractSection:
        return GeneratedContractSection(
            id=m.id,
            generated_contract_id=m.generated_contract_id,
            template_section_id=m.template_section_id,
            section_key=m.section_key,
            sort_order=m.sort_order,
            rendered_text=m.rendered_text,
            render_state=m.render_state,
            skip_reason=m.skip_reason,
            created_at=m.created_at,
        )

    @staticmethod
    def _artifact_to_domain(m: orm.GeneratedContractArtifactModel) -> GeneratedContractArtifact:
        return GeneratedContractArtifact(
            id=m.id,
            generated_contract_id=m.generated_contract_id,
            artifact_type=m.artifact_type,
            storage_url=m.storage_url,
            checksum=m.checksum,
            created_at=m.created_at,
        )

    @staticmethod
    def _to_domain(m: orm.GeneratedContractModel) -> GeneratedContract:
        return GeneratedContract(
            id=m.id,
            contract_template_id=m.contract_template_id,
            template_version_id=m.template_version_id,
            organization_id=m.organization_id,
            crm_contact_id=m.crm_contact_id,
            crm_property_id=m.crm_property_id,
            status=GeneratedContractStatus(m.status),
            input_payload_json=m.input_payload_json,
            rendered_schema_json=m.rendered_schema_json,
            created_at=m.created_at,
            updated_at=m.updated_at,
            parties=[SqlAlchemyGeneratedContractRepository._party_to_domain(p) for p in m.parties],
            sections=[
                SqlAlchemyGeneratedContractRepository._section_to_domain(s) for s in m.sections
            ],
            artifacts=[
                SqlAlchemyGeneratedContractRepository._artifact_to_domain(a) for a in m.artifacts
            ],
        )

    # -- repository methods --------------------------------------------------

    async def save(self, contract: GeneratedContract) -> GeneratedContract:
        row = orm.GeneratedContractModel(
            id=contract.id,
            contract_template_id=contract.contract_template_id,
            template_version_id=contract.template_version_id,
            organization_id=contract.organization_id,
            crm_contact_id=contract.crm_contact_id,
            crm_property_id=contract.crm_property_id,
            status=contract.status.value,
            input_payload_json=contract.input_payload_json,
            rendered_schema_json=contract.rendered_schema_json,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        contract.created_at = row.created_at
        contract.updated_at = row.updated_at
        return contract

    async def get_by_id(self, contract_id: UUID) -> GeneratedContract | None:
        stmt = (
            select(orm.GeneratedContractModel)
            .where(orm.GeneratedContractModel.id == contract_id)
            .options(
                selectinload(orm.GeneratedContractModel.parties),
                selectinload(orm.GeneratedContractModel.sections),
                selectinload(orm.GeneratedContractModel.artifacts),
            )
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def update(self, contract: GeneratedContract) -> None:
        row = await self._session.get(orm.GeneratedContractModel, contract.id)
        if row:
            row.status = contract.status.value
            row.input_payload_json = contract.input_payload_json
            row.rendered_schema_json = contract.rendered_schema_json
            await self._session.flush()

    async def save_artifact(self, artifact: GeneratedContractArtifact) -> GeneratedContractArtifact:
        row = orm.GeneratedContractArtifactModel(
            id=artifact.id,
            generated_contract_id=artifact.generated_contract_id,
            artifact_type=artifact.artifact_type,
            storage_url=artifact.storage_url,
            checksum=artifact.checksum,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        artifact.created_at = row.created_at
        return artifact
