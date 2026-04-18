from datetime import UTC, datetime
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from screening.adapters.database.models import (
    ApplicantModel,
    DocumentModel,
    EventModel,
    ExtractedDataModel,
    IntakeFormRequestModel,
    ScreeningReportModel,
    SubmissionModel,
)
from screening.application.crypto import compute_blind_index, decrypt_field, encrypt_field
from screening.domain.models import (
    Applicant,
    Document,
    DocumentStatus,
    DocumentType,
    EventType,
    ScreeningAuditEvent,
    ExtractedData,
    ExtractionStatus,
    IntakeFormRequest,
    IntakeFormRequestStatus,
    ListingType,
    PropertyType,
    RiskLevel,
    ScreeningReport,
    Submission,
    SubmissionStatus,
)


class SqlAlchemyApplicantRepository:
    def __init__(
        self,
        session: AsyncSession,
        public_key: RSAPublicKey,
        private_key: RSAPrivateKey,
        hmac_key: bytes,
    ) -> None:
        self._session = session
        self._public_key = public_key
        self._private_key = private_key
        self._hmac_key = hmac_key

    async def save(self, applicant: Applicant) -> Applicant:
        encrypted_nif = encrypt_field(applicant.nif, self._public_key)
        nif_hash = compute_blind_index(applicant.nif, self._hmac_key)

        model = ApplicantModel(
            id=applicant.id,
            nif=encrypted_nif,
            nif_hash=nif_hash,
            name=applicant.name,
            date_of_birth=applicant.date_of_birth,
            email=applicant.email,
            organization_id=applicant.organization_id,
            form_request_id=applicant.form_request_id,
            listing_type=applicant.listing_type.value,
            property_type=applicant.property_type.value if applicant.property_type else None,
            phone=applicant.phone,
            property_value=applicant.property_value,
            monthly_rent=applicant.monthly_rent,
            property_title=applicant.property_title,
            property_address=applicant.property_address,
        )
        self._session.add(model)
        await self._session.flush()
        return applicant

    async def get_by_id(self, applicant_id: UUID) -> Applicant | None:
        result = await self._session.execute(
            select(ApplicantModel).where(ApplicantModel.id == applicant_id)
        )
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def get_by_nif(self, nif: str) -> Applicant | None:
        nif_hash = compute_blind_index(nif, self._hmac_key)
        result = await self._session.execute(
            select(ApplicantModel).where(ApplicantModel.nif_hash == nif_hash)
        )
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def list_by_organization_id(self, organization_id: UUID) -> list[Applicant]:
        result = await self._session.execute(
            select(ApplicantModel)
            .where(ApplicantModel.organization_id == organization_id)
            .order_by(ApplicantModel.id)
        )
        return [self._to_domain(m) for m in result.scalars().all()]

    def _to_domain(self, model: ApplicantModel) -> Applicant:
        decrypted_nif = decrypt_field(model.nif, self._private_key)
        return Applicant(
            id=model.id,
            nif=decrypted_nif,
            name=model.name,
            date_of_birth=model.date_of_birth,
            email=model.email,
            organization_id=model.organization_id,
            form_request_id=model.form_request_id,
            listing_type=ListingType(model.listing_type),
            property_type=PropertyType(model.property_type) if model.property_type else None,
            phone=model.phone,
            property_value=model.property_value,
            monthly_rent=model.monthly_rent,
            property_title=model.property_title,
            property_address=model.property_address,
        )


class SqlAlchemyDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, document: Document) -> Document:
        model = DocumentModel(
            id=document.id,
            applicant_id=document.applicant_id,
            s3_key=document.s3_key,
            original_filename=document.original_filename,
            content_type=document.content_type,
            document_type=document.document_type.value,
            status=document.status.value,
            reducto_document_id=document.reducto_document_id,
        )
        self._session.add(model)
        await self._session.flush()
        return document

    async def get_by_id(self, document_id: UUID) -> Document | None:
        result = await self._session.execute(
            select(DocumentModel).where(DocumentModel.id == document_id)
        )
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def get_by_applicant_id(self, applicant_id: UUID) -> list[Document]:
        result = await self._session.execute(
            select(DocumentModel).where(DocumentModel.applicant_id == applicant_id)
        )
        return [self._to_domain(m) for m in result.scalars().all()]

    async def update(self, document: Document) -> Document:
        result = await self._session.execute(
            select(DocumentModel).where(DocumentModel.id == document.id)
        )
        model = result.scalar_one_or_none()
        if model:
            model.status = document.status.value
            model.reducto_document_id = document.reducto_document_id
            await self._session.flush()
        return document

    @staticmethod
    def _to_domain(model: DocumentModel) -> Document:
        return Document(
            id=model.id,
            applicant_id=model.applicant_id,
            s3_key=model.s3_key,
            original_filename=model.original_filename,
            content_type=model.content_type,
            document_type=DocumentType(model.document_type),
            status=DocumentStatus(model.status),
            reducto_document_id=model.reducto_document_id,
        )


class SqlAlchemyExtractedDataRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, extracted_data: ExtractedData) -> ExtractedData:
        model = ExtractedDataModel(
            id=extracted_data.id,
            document_id=extracted_data.document_id,
            extracted_content=extracted_data.extracted_content,
            extraction_status=extracted_data.extraction_status.value,
        )
        self._session.add(model)
        await self._session.flush()
        return extracted_data

    async def get_by_document_id(self, document_id: UUID) -> ExtractedData | None:
        result = await self._session.execute(
            select(ExtractedDataModel).where(ExtractedDataModel.document_id == document_id)
        )
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    @staticmethod
    def _to_domain(model: ExtractedDataModel) -> ExtractedData:
        return ExtractedData(
            id=model.id,
            document_id=model.document_id,
            extracted_content=model.extracted_content,
            extraction_status=ExtractionStatus(model.extraction_status),
        )


class SqlAlchemyScreeningReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, report: ScreeningReport) -> ScreeningReport:
        model = ScreeningReportModel(
            id=report.id,
            applicant_id=report.applicant_id,
            risk_level=report.risk_level.value,
            identity_verified=report.identity_verified,
            income_verified=report.income_verified,
            dti_ratio=report.dti_ratio,
            justification=report.justification,
            listing_type=report.listing_type.value,
            property_type=report.property_type.value if report.property_type else None,
            average_monthly_income=report.average_monthly_income,
        )
        self._session.add(model)
        await self._session.flush()
        return report

    async def get_by_applicant_id(self, applicant_id: UUID) -> ScreeningReport | None:
        result = await self._session.execute(
            select(ScreeningReportModel).where(ScreeningReportModel.applicant_id == applicant_id)
        )
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    @staticmethod
    def _to_domain(model: ScreeningReportModel) -> ScreeningReport:
        return ScreeningReport(
            id=model.id,
            applicant_id=model.applicant_id,
            risk_level=RiskLevel(model.risk_level),
            identity_verified=model.identity_verified,
            income_verified=model.income_verified,
            dti_ratio=model.dti_ratio,
            justification=model.justification,
            listing_type=ListingType(model.listing_type),
            property_type=PropertyType(model.property_type) if model.property_type else None,
            average_monthly_income=model.average_monthly_income,
        )


class SqlAlchemyEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, event: ScreeningAuditEvent) -> ScreeningAuditEvent:
        model = EventModel(
            id=event.id,
            applicant_id=event.applicant_id,
            event_type=event.event_type.value,
            payload=event.payload,
            created_at=event.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return event

    async def get_by_applicant_id(self, applicant_id: UUID) -> list[ScreeningAuditEvent]:
        result = await self._session.execute(
            select(EventModel)
            .where(EventModel.applicant_id == applicant_id)
            .order_by(EventModel.created_at)
        )
        return [self._to_domain(m) for m in result.scalars().all()]

    @staticmethod
    def _to_domain(model: EventModel) -> ScreeningAuditEvent:
        return ScreeningAuditEvent(
            id=model.id,
            applicant_id=model.applicant_id,
            event_type=EventType(model.event_type),
            payload=model.payload,
            created_at=model.created_at,
        )


class SqlAlchemyIntakeFormRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, request: IntakeFormRequest) -> IntakeFormRequest:
        model = IntakeFormRequestModel(
            id=request.id,
            organization_id=request.organization_id,
            applicant_name=request.applicant_name,
            applicant_email=request.applicant_email,
            applicant_phone=request.applicant_phone,
            property_id=request.property_id,
            listing_type=request.listing_type.value,
            property_type=request.property_type.value if request.property_type else None,
            property_title=request.property_title,
            property_price=request.property_price,
            property_address=request.property_address,
            status=request.status.value,
            created_at=request.created_at,
            updated_at=request.updated_at,
        )
        self._session.add(model)
        await self._session.flush()
        return request

    async def get_by_id(self, request_id: UUID) -> IntakeFormRequest | None:
        result = await self._session.execute(
            select(IntakeFormRequestModel).where(IntakeFormRequestModel.id == request_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def list_by_organization_id(
        self, organization_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[IntakeFormRequest]:
        result = await self._session.execute(
            select(IntakeFormRequestModel)
            .where(IntakeFormRequestModel.organization_id == organization_id)
            .order_by(IntakeFormRequestModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [self._to_domain(m) for m in result.scalars().all()]

    async def update_status(self, request_id: UUID, status: IntakeFormRequestStatus) -> None:
        await self._session.execute(
            update(IntakeFormRequestModel)
            .where(IntakeFormRequestModel.id == request_id)
            .values(status=status.value, updated_at=datetime.now(UTC))
        )
        await self._session.flush()

    def _to_domain(self, model: IntakeFormRequestModel) -> IntakeFormRequest:
        return IntakeFormRequest(
            id=model.id,
            organization_id=model.organization_id,
            applicant_name=model.applicant_name,
            applicant_email=model.applicant_email,
            applicant_phone=model.applicant_phone,
            property_id=model.property_id,
            listing_type=ListingType(model.listing_type),
            property_type=PropertyType(model.property_type) if model.property_type else None,
            property_title=model.property_title,
            property_price=model.property_price,
            property_address=model.property_address,
            status=IntakeFormRequestStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class SqlAlchemySubmissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, submission: Submission) -> Submission:
        model = SubmissionModel(
            id=submission.id,
            applicant_id=submission.applicant_id,
            form_request_id=submission.form_request_id,
            organization_id=submission.organization_id,
            terms_accepted=submission.terms_accepted,
            status=submission.status.value,
            created_at=submission.created_at,
            updated_at=submission.updated_at,
        )
        self._session.add(model)
        await self._session.flush()
        return submission

    async def get_by_id(self, submission_id: UUID) -> Submission | None:
        result = await self._session.execute(
            select(SubmissionModel).where(SubmissionModel.id == submission_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def get_by_applicant_id(self, applicant_id: UUID) -> Submission | None:
        result = await self._session.execute(
            select(SubmissionModel).where(SubmissionModel.applicant_id == applicant_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def get_by_form_request_id(self, form_request_id: UUID) -> Submission | None:
        result = await self._session.execute(
            select(SubmissionModel).where(SubmissionModel.form_request_id == form_request_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def update(self, submission: Submission) -> Submission:
        await self._session.execute(
            update(SubmissionModel)
            .where(SubmissionModel.id == submission.id)
            .values(
                applicant_id=submission.applicant_id,
                status=submission.status.value,
                updated_at=datetime.now(UTC),
            )
        )
        await self._session.flush()
        return submission

    def _to_domain(self, model: SubmissionModel) -> Submission:
        return Submission(
            id=model.id,
            applicant_id=model.applicant_id,
            form_request_id=model.form_request_id,
            organization_id=model.organization_id,
            terms_accepted=model.terms_accepted,
            status=SubmissionStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
