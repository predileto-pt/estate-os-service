from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from properties.adapters.database.models import (
    DocumentContentModel,
    ExtractionJobModel,
    PropertyImageModel,
    PropertyModel,
    PropertyOwnerModel,
    PropertyPriceModel,
)
from properties.application.ports.repositories.document_content_repository import (
    DocumentContentRepository,
)
from properties.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.models.document_content import DocumentContent
from properties.domain.models.extraction_job import ExtractionJob, ExtractionJobStatus
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_characteristics import PropertyCharacteristics
from properties.domain.models.property_image import PropertyImage
from properties.domain.models.property_owner import (
    CivilStatus,
    DocumentType,
    PropertyOwner,
)
from properties.domain.models.property_price import PropertyPrice


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
            email=m.email,
            phone_number=m.phone_number,
            email_verified=m.email_verified,
            phone_verified=m.phone_verified,
        )

    @staticmethod
    def _price_to_domain(m: PropertyPriceModel) -> PropertyPrice:
        lt = m.listing_type
        listing_type = ListingType(lt.value if hasattr(lt, "value") else lt)
        return PropertyPrice(
            id=UUID(m.id),
            property_id=UUID(m.property_id),
            amount=Decimal(str(m.amount)),
            listing_type=listing_type,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _image_to_domain(m: PropertyImageModel) -> PropertyImage:
        return PropertyImage(
            id=UUID(m.id),
            property_id=UUID(m.property_id),
            s3_key=m.s3_key,
            filename=m.filename,
            content_type=m.content_type,
            size_bytes=m.size_bytes,
            display_order=m.display_order,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _to_domain(
        m: PropertyModel,
        owners: list[PropertyOwnerModel],
        prices: list[PropertyPriceModel] | None = None,
        images: list[PropertyImageModel] | None = None,
    ) -> Property:
        return Property(
            id=UUID(m.id),
            organization_id=UUID(m.organization_id),
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
            latitude=m.latitude,
            longitude=m.longitude,
            owners=[SqlAlchemyPropertyRepository._owner_to_domain(o) for o in owners],
            prices=[SqlAlchemyPropertyRepository._price_to_domain(p) for p in (prices or [])],
            images=[SqlAlchemyPropertyRepository._image_to_domain(i) for i in (images or [])],
        )

    async def _load_owners(self, property_id: str) -> list[PropertyOwnerModel]:
        result = await self._session.execute(
            select(PropertyOwnerModel).where(PropertyOwnerModel.property_id == property_id)
        )
        return list(result.scalars().all())

    async def _load_images(self, property_id: str) -> list[PropertyImageModel]:
        result = await self._session.execute(
            select(PropertyImageModel)
            .where(PropertyImageModel.property_id == property_id)
            .order_by(PropertyImageModel.display_order.asc())
        )
        return list(result.scalars().all())

    async def _load_prices(self, property_id: str) -> list[PropertyPriceModel]:
        result = await self._session.execute(
            select(PropertyPriceModel)
            .where(PropertyPriceModel.property_id == property_id)
            .order_by(PropertyPriceModel.created_at.desc())
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
        prices = await self._load_prices(row.id)
        images = await self._load_images(row.id)
        return self._to_domain(row, owners, prices, images)

    async def list_by_organization(self, organization_id: UUID) -> list[Property]:
        result = await self._session.execute(
            select(PropertyModel)
            .where(PropertyModel.organization_id == str(organization_id))
            .order_by(PropertyModel.created_at.desc())
        )
        properties = []
        for row in result.scalars().all():
            owners = await self._load_owners(row.id)
            prices = await self._load_prices(row.id)
            images = await self._load_images(row.id)
            properties.append(self._to_domain(row, owners, prices, images))
        return properties

    async def list_active(self) -> list[Property]:
        result = await self._session.execute(
            select(PropertyModel)
            .where(PropertyModel.status == PropertyStatus.ACTIVE)
            .order_by(PropertyModel.created_at.desc())
        )
        properties = []
        for row in result.scalars().all():
            owners = await self._load_owners(row.id)
            prices = await self._load_prices(row.id)
            images = await self._load_images(row.id)
            properties.append(self._to_domain(row, owners, prices, images))
        return properties

    async def save(self, prop: Property) -> Property:
        model = PropertyModel(
            id=str(prop.id),
            organization_id=str(prop.organization_id),
            address=prop.address,
            listing_type=prop.listing_type.value,
            typology=prop.typology.value,
            status=prop.status.value,
            description=prop.description,
            characteristics=prop.characteristics.to_dict() if prop.characteristics else None,
            latitude=prop.latitude,
            longitude=prop.longitude,
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
            email=owner.email,
            phone_number=owner.phone_number,
            email_verified=owner.email_verified,
            phone_verified=owner.phone_verified,
        )
        self._session.add(owner_model)
        await self._session.flush()
        return await self.get_by_id(prop.id)

    async def update_owner(self, prop: Property, owner: PropertyOwner) -> Property:
        result = await self._session.execute(
            select(PropertyOwnerModel).where(PropertyOwnerModel.id == str(owner.id))
        )
        model = result.scalar_one()
        model.email = owner.email
        model.phone_number = owner.phone_number
        model.email_verified = owner.email_verified
        model.phone_verified = owner.phone_verified
        await self._session.flush()
        return await self.get_by_id(prop.id)

    async def save_price(self, prop: Property, price: PropertyPrice) -> Property:
        price_model = PropertyPriceModel(
            id=str(price.id),
            property_id=str(prop.id),
            amount=float(price.amount),
            listing_type=price.listing_type.value,
        )
        self._session.add(price_model)
        await self._session.flush()
        return await self.get_by_id(prop.id)

    async def save_image(self, prop: Property, image: PropertyImage) -> Property:
        image_model = PropertyImageModel(
            id=str(image.id),
            property_id=str(prop.id),
            s3_key=image.s3_key,
            filename=image.filename,
            content_type=image.content_type,
            size_bytes=image.size_bytes,
            display_order=image.display_order,
        )
        self._session.add(image_model)
        await self._session.flush()
        return await self.get_by_id(prop.id)

    async def delete_image(self, prop: Property, image_id: UUID) -> Property:
        result = await self._session.execute(
            select(PropertyImageModel).where(PropertyImageModel.id == str(image_id))
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()
        return await self.get_by_id(prop.id)

    async def update_image_orders(
        self, prop: Property, image_orders: list[tuple[UUID, int]]
    ) -> Property:
        for image_id, order in image_orders:
            result = await self._session.execute(
                select(PropertyImageModel).where(PropertyImageModel.id == str(image_id))
            )
            model = result.scalar_one()
            model.display_order = order
        await self._session.flush()
        return await self.get_by_id(prop.id)

    async def delete(self, property_id: UUID) -> None:
        pid = str(property_id)
        # Delete child rows first to satisfy FK constraints (no ondelete=CASCADE).
        # Order: owners, prices, images, then the property itself.
        # extraction_jobs.property_id is nullable and handled by the
        # ExtractionJobRepository.delete_by_property_id() before this is called.
        # property_pois has ON DELETE CASCADE so it's wiped automatically.
        for model_cls, fk_column in (
            (PropertyOwnerModel, PropertyOwnerModel.property_id),
            (PropertyPriceModel, PropertyPriceModel.property_id),
            (PropertyImageModel, PropertyImageModel.property_id),
        ):
            await self._session.execute(delete(model_cls).where(fk_column == pid))

        await self._session.execute(delete(PropertyModel).where(PropertyModel.id == pid))
        await self._session.flush()

    async def update_status(self, property_id: UUID, status: PropertyStatus) -> None:
        result = await self._session.execute(
            select(PropertyModel).where(PropertyModel.id == str(property_id))
        )
        model = result.scalar_one_or_none()
        if not model:
            from properties.domain.exceptions import PropertyNotFoundError

            raise PropertyNotFoundError(str(property_id))
        model.status = status
        await self._session.flush()

    async def update_address(self, property_id: UUID, address: str) -> None:
        result = await self._session.execute(
            select(PropertyModel).where(PropertyModel.id == str(property_id))
        )
        model = result.scalar_one_or_none()
        if not model:
            from properties.domain.exceptions import PropertyNotFoundError

            raise PropertyNotFoundError(str(property_id))
        model.address = address
        await self._session.flush()

    async def bump_aggregate_version(self, property_id: UUID) -> Property:
        result = await self._session.execute(
            select(PropertyModel).where(PropertyModel.id == str(property_id))
        )
        model = result.scalar_one_or_none()
        if not model:
            from properties.domain.exceptions import PropertyNotFoundError

            raise PropertyNotFoundError(str(property_id))
        model.aggregate_version = (model.aggregate_version or 0) + 1
        await self._session.flush()
        return await self.get_by_id(property_id)


# ── ExtractionJob ───────────────────────────────────────────────────────────


class SqlAlchemyExtractionJobRepository(ExtractionJobRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(m: ExtractionJobModel) -> ExtractionJob:
        return ExtractionJob(
            id=UUID(m.id),
            user_id=UUID(m.user_id),
            organization_id=UUID(m.organization_id),
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
            organization_id=str(job.organization_id),
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

    async def list_by_organization(self, organization_id: UUID) -> list[ExtractionJob]:
        result = await self._session.execute(
            select(ExtractionJobModel)
            .where(ExtractionJobModel.organization_id == str(organization_id))
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

    async def delete_by_property_id(self, property_id: UUID) -> None:
        pid = str(property_id)
        # Find the job IDs first so we can cascade delete document_contents
        # (FK extraction_jobs.id has no ondelete=CASCADE).
        result = await self._session.execute(
            select(ExtractionJobModel.id).where(ExtractionJobModel.property_id == pid)
        )
        job_ids = [row[0] for row in result.all()]
        if not job_ids:
            return

        await self._session.execute(
            delete(DocumentContentModel).where(DocumentContentModel.extraction_job_id.in_(job_ids))
        )
        await self._session.execute(
            delete(ExtractionJobModel).where(ExtractionJobModel.id.in_(job_ids))
        )
        await self._session.flush()


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
            extraction_reasoning=m.extraction_reasoning,
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
            extraction_reasoning=content.extraction_reasoning,
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
                extraction_reasoning=content.extraction_reasoning,
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

    async def update_extraction_reasoning(
        self, content_id: UUID, extraction_reasoning: str
    ) -> None:
        result = await self._session.execute(
            select(DocumentContentModel).where(DocumentContentModel.id == str(content_id))
        )
        model = result.scalar_one()
        model.extraction_reasoning = extraction_reasoning
        await self._session.flush()
