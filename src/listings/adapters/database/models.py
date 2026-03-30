"""Read-only ORM models for the listings bounded context.

These map to the same physical tables as properties but are owned
by this context for read-only queries. This avoids cross-context imports.
"""

import enum
from datetime import datetime

from sqlalchemy import Enum, Float, Integer, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.models import Base


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


class ReadPropertyModel(Base):
    """Read-only view of the properties table."""

    __tablename__ = "properties"
    __table_args__ = {"extend_existing": True}

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    listing_type: Mapped[ListingType] = mapped_column(
        Enum(ListingType, name="listing_type", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    typology: Mapped[Typology] = mapped_column(
        Enum(Typology, name="typology", values_callable=lambda e: [x.value for x in e]),
        nullable=False,
    )
    status: Mapped[PropertyStatus] = mapped_column(
        Enum(
            PropertyStatus,
            name="property_status",
            values_callable=lambda e: [x.value for x in e],
        ),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text)
    characteristics: Mapped[dict | None] = mapped_column(JSONB)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())


class ReadPropertyPriceModel(Base):
    """Read-only view of the property_prices table."""

    __tablename__ = "property_prices"
    __table_args__ = {"extend_existing": True}

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    property_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
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


class ReadPropertyImageModel(Base):
    """Read-only view of the property_images table."""

    __tablename__ = "property_images"
    __table_args__ = {"extend_existing": True}

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    property_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
