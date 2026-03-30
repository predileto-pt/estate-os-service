from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.models import Base


class BookingApplicantModel(Base):
    __tablename__ = "booking_applicants"
    __table_args__ = (UniqueConstraint("external_id", name="uq_booking_applicants_external_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    supabase_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(10), nullable=False, server_default="LOW")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class BookingSlotModel(Base):
    __tablename__ = "booking_slots"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="ck_booking_slots_valid_time_range"),
        CheckConstraint(
            "status IN ('available', 'booked', 'cancelled')",
            name="ck_booking_slots_status",
        ),
        Index("idx_booking_slots_property_status", "property_id", "status"),
        Index("idx_booking_slots_agent", "agent_user_id"),
        Index("idx_booking_slots_org", "organization_id"),
        Index("idx_booking_slots_start_time", "start_time"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    agent_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="available")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )


class BookingBookingModel(Base):
    __tablename__ = "booking_bookings"
    __table_args__ = (
        UniqueConstraint("slot_id", name="uq_booking_bookings_slot_id"),
        CheckConstraint(
            "status IN ('confirmed', 'cancelled_by_applicant', 'cancelled_by_agent')",
            name="ck_booking_bookings_status",
        ),
        Index("idx_booking_bookings_applicant", "applicant_id"),
        Index("idx_booking_bookings_property", "property_id"),
        Index("idx_booking_bookings_org", "organization_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slot_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("booking_slots.id"), nullable=False)
    applicant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("booking_applicants.id"), nullable=False
    )
    property_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="confirmed")
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
