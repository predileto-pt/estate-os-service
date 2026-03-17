from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from property_management.adapters.database.models import (
    DocumentContentModel,
    ExtractionJobModel,
    PropertyModel,
    PropertyOwnerModel,
)
from property_management.application.ports.repositories.document_content_repository import (
    DocumentContentRepository,
)
from property_management.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.models.document_content import DocumentContent
from property_management.domain.models.extraction_job import ExtractionJob, ExtractionJobStatus
from property_management.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from property_management.domain.models.property_characteristics import PropertyCharacteristics
from property_management.domain.models.property_owner import (
    CivilStatus,
    DocumentType,
    PropertyOwner,
)


# ── Property ────────────────────────────────────────────────────────────────


class SqlAlchemyPropertyRepository(PropertyRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _owner_to_domain(m: PropertyOwnerModel) -> PropertyOwner:
        return PropertyOwner(
            id=UUID(m.id),
            property_id=UUID(m.property_id),
            full_name=m.full_name,
            civil_status=CivilStatus(m.civil_status.value) if m.civil_status else None,
            address=m.address,
            nif=m.nif,
            document_type=DocumentType(m.document_type.value) if m.document_type else None,
            document_id=m.document_id,
            issued_by=m.issued_by,
            issuing_district=m.issuing_district,
            date_of_birth=m.date_of_birth,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _to_domain(m: PropertyModel, owners: list[PropertyOwnerModel]) -> Property:
        return Property(
            id=UUID(m.id),
            user_id=UUID(m.user_id),
            address=m.address,
            listing_type=ListingType(m.listing_type.value),
            typology=Typology(m.typology.value),
            status=PropertyStatus(m.status.value),
            description=m.description,
            created_at=m.created_at,
            updated_at=m.updated_at,
            characteristics=(
                PropertyCharacteristics.from_dict(m.characteristics) if m.characteristics else None
            ),
            owners=[SqlAlchemyPropertyRepository._owner_to_domain(o) for o in owners],
        )

    async def _load_owners(self, property_id: str) -> list[PropertyOwnerModel]:
        result = await self._session.execute(
            select(PropertyOwnerModel).where(PropertyOwnerModel.property_id == property_id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, property_id: UUID) -> Property | None:
        result = await self._session.execute(
            select(PropertyModel).where(PropertyModel.id == str(property_id))
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        owners = await self._load_owners(row.id)
        return self._to_domain(row, owners)

    async def list_by_user(self, user_id: UUID) -> list[Property]:
        result = await self._session.execute(
            select(PropertyModel)
            .where(PropertyModel.user_id == str(user_id))
            .order_by(PropertyModel.created_at.desc())
        )
        properties = []
        for row in result.scalars().all():
            owners = await self._load_owners(row.id)
            properties.append(self._to_domain(row, owners))
        return properties

    async def save(self, prop: Property) -> Property:
        model = PropertyModel(
            id=str(prop.id),
            user_id=str(prop.user_id),
            address=prop.address,
            listing_type=prop.listing_type.value,
            typology=prop.typology.value,
            status=prop.status.value,
            description=prop.description,
            characteristics=prop.characteristics.to_dict() if prop.characteristics else None,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model, [])

    async def save_owner(self, prop: Property, owner: PropertyOwner) -> Property:
        owner_model = PropertyOwnerModel(
            id=str(owner.id),
            property_id=str(prop.id),
            full_name=owner.full_name,
            civil_status=owner.civil_status.value if owner.civil_status else None,
            address=owner.address,
            nif=owner.nif,
            document_type=owner.document_type.value if owner.document_type else None,
            document_id=owner.document_id,
            issued_by=owner.issued_by,
            issuing_district=owner.issuing_district,
            date_of_birth=owner.date_of_birth,
        )
        self._session.add(owner_model)
        await self._session.flush()
        return await self.get_by_id(prop.id)


# ── ExtractionJob ───────────────────────────────────────────────────────────


class SqlAlchemyExtractionJobRepository(ExtractionJobRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(m: ExtractionJobModel) -> ExtractionJob:
        return ExtractionJob(
            id=UUID(m.id),
            user_id=UUID(m.user_id),
            status=ExtractionJobStatus(m.status.value),
            document_keys=m.document_keys or [],
            listing_type=m.listing_type,
            typology=m.typology,
            property_id=UUID(m.property_id) if m.property_id else None,
            error_message=m.error_message,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    async def save(self, job: ExtractionJob) -> ExtractionJob:
        model = ExtractionJobModel(
            id=str(job.id),
            user_id=str(job.user_id),
            status=job.status.value,
            document_keys=job.document_keys,
            listing_type=job.listing_type,
            typology=job.typology,
            property_id=str(job.property_id) if job.property_id else None,
            error_message=job.error_message,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def get_by_id(self, job_id: UUID) -> ExtractionJob | None:
        result = await self._session.execute(
            select(ExtractionJobModel).where(ExtractionJobModel.id == str(job_id))
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def list_by_user(self, user_id: UUID) -> list[ExtractionJob]:
        result = await self._session.execute(
            select(ExtractionJobModel)
            .where(ExtractionJobModel.user_id == str(user_id))
            .order_by(ExtractionJobModel.created_at.desc())
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def update(self, job: ExtractionJob) -> ExtractionJob:
        result = await self._session.execute(
            select(ExtractionJobModel).where(ExtractionJobModel.id == str(job.id))
        )
        model = result.scalar_one()
        model.status = job.status.value
        model.document_keys = job.document_keys
        model.listing_type = job.listing_type
        model.typology = job.typology
        model.property_id = str(job.property_id) if job.property_id else None
        model.error_message = job.error_message
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)


# ── DocumentContent ─────────────────────────────────────────────────────────


class SqlAlchemyDocumentContentRepository(DocumentContentRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(m: DocumentContentModel) -> DocumentContent:
        return DocumentContent(
            id=UUID(m.id),
            extraction_job_id=UUID(m.extraction_job_id),
            document_index=m.document_index,
            document_key=m.document_key,
            parsed_text=m.parsed_text,
            category=m.category,
            document_subtype=m.document_subtype,
            created_at=m.created_at,
        )

    async def save(self, content: DocumentContent) -> DocumentContent:
        model = DocumentContentModel(
            id=str(content.id),
            extraction_job_id=str(content.extraction_job_id),
            document_index=content.document_index,
            document_key=content.document_key,
            parsed_text=content.parsed_text,
            category=content.category,
            document_subtype=content.document_subtype,
        )
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def save_batch(self, contents: list[DocumentContent]) -> list[DocumentContent]:
        models = []
        for content in contents:
            model = DocumentContentModel(
                id=str(content.id),
                extraction_job_id=str(content.extraction_job_id),
                document_index=content.document_index,
                document_key=content.document_key,
                parsed_text=content.parsed_text,
                category=content.category,
                document_subtype=content.document_subtype,
            )
            self._session.add(model)
            models.append(model)
        await self._session.flush()
        for model in models:
            await self._session.refresh(model)
        return [self._to_domain(m) for m in models]

    async def get_by_job_id(self, job_id: UUID) -> list[DocumentContent]:
        result = await self._session.execute(
            select(DocumentContentModel)
            .where(DocumentContentModel.extraction_job_id == str(job_id))
            .order_by(DocumentContentModel.document_index)
        )
        return [self._to_domain(row) for row in result.scalars().all()]

    async def update_classification(
        self, content_id: UUID, category: str, document_subtype: str
    ) -> None:
        result = await self._session.execute(
            select(DocumentContentModel).where(DocumentContentModel.id == str(content_id))
        )
        model = result.scalar_one()
        model.category = category
        model.document_subtype = document_subtype
        await self._session.flush()
