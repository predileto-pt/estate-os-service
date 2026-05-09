import enum
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.models import Base


# ── Enums ────────────────────────────────────────────────────────────────────


class ListingType(str, enum.Enum):
    SALE = "sale"
    PURCHASE = "purchase"


class Typology(str, enum.Enum):
    HOUSE = "house"
    APARTMENT = "apartment"
    LAND = "land"
    RUIN = "ruin"


class PropertyStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SOLD = "sold"
    RENTED = "rented"
    WITHDRAWN = "withdrawn"


class CivilStatus(str, enum.Enum):
    SINGLE = "single"
    MARRIED = "married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"
    CIVIL_UNION = "civil_union"
    SEPARATED = "separated"


class DocumentType(str, enum.Enum):
    CARTAO_CIDADAO = "cartao_cidadao"
    PASSPORT = "passport"
    VISTO_RESIDENCIA = "visto_residencia"
    TITULO_RESIDENCIA = "titulo_residencia"


# ── Models ───────────────────────────────────────────────────────────────────


class PropertyModel(Base):
    __tablename__ = "properties"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False
    )
    address: Mapped[str] = mapped_column(Text, nullable=False)
    listing_type: Mapped[ListingType] = mapped_column(
        Enum(
            ListingType,
            name="listing_type",
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
    )
    typology: Mapped[Typology] = mapped_column(
        Enum(
            Typology,
            name="typology",
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
    )
    status: Mapped[PropertyStatus] = mapped_column(
        Enum(
            PropertyStatus,
            name="property_status",
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
        server_default="draft",
    )
    description: Mapped[str | None] = mapped_column(Text)
    characteristics: Mapped[dict | None] = mapped_column(JSONB)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    # Idempotency source for the property_listings projector.
    aggregate_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_properties_organization_id", "organization_id"),)


class PropertyOwnerModel(Base):
    __tablename__ = "property_owners"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    property_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("properties.id"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    civil_status: Mapped[CivilStatus | None] = mapped_column(
        Enum(
            CivilStatus,
            name="civil_status",
            values_callable=lambda e: [x.value for x in e],
        ),
    )
    address: Mapped[str] = mapped_column(Text, nullable=False)
    nif: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[DocumentType | None] = mapped_column(
        Enum(
            DocumentType,
            name="document_type",
            values_callable=lambda e: [x.value for x in e],
        ),
    )
    document_id: Mapped[str | None] = mapped_column(Text)
    issued_by: Mapped[str | None] = mapped_column(Text)
    issuing_district: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    email: Mapped[str | None] = mapped_column(Text)
    phone_number: Mapped[str | None] = mapped_column(Text)
    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    phone_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_property_owners_property_id", "property_id"),)


class PropertyPriceModel(Base):
    __tablename__ = "property_prices"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    property_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("properties.id"), nullable=False
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    listing_type: Mapped[ListingType] = mapped_column(
        Enum(
            ListingType,
            name="listing_type",
            values_callable=lambda e: [x.value for x in e],
            create_type=False,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_property_prices_property_id", "property_id"),)


class PropertyImageModel(Base):
    __tablename__ = "property_images"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    property_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("properties.id"), nullable=False
    )
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_property_images_property_id", "property_id"),)


class ExtractionJobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ExtractionJobModel(Base):
    __tablename__ = "extraction_jobs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    organization_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False
    )
    status: Mapped[ExtractionJobStatus] = mapped_column(
        Enum(
            ExtractionJobStatus,
            name="extraction_job_status",
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
        server_default="pending",
    )
    document_keys: Mapped[list] = mapped_column(JSONB, nullable=False)
    listing_type: Mapped[str | None] = mapped_column(Text)
    typology: Mapped[str | None] = mapped_column(Text)
    property_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("properties.id")
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_extraction_jobs_user_id", "user_id"),
        Index("idx_extraction_jobs_organization_id", "organization_id"),
    )


class DocumentContentModel(Base):
    __tablename__ = "document_contents"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    extraction_job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("extraction_jobs.id"), nullable=False
    )
    document_index: Mapped[int] = mapped_column(nullable=False)
    document_key: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    document_subtype: Mapped[str | None] = mapped_column(Text)
    extraction_reasoning: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_document_contents_job_id", "extraction_job_id"),)
