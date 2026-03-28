from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.models import Base


class ApplicantModel(Base):
    __tablename__ = "applicant_applicants"
    __table_args__ = (UniqueConstraint("nif_hash", "form_request_id", name="uq_applicants_nif_form_request"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    nif: Mapped[str] = mapped_column(String(512))
    nif_hash: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    date_of_birth: Mapped[date] = mapped_column()
    email: Mapped[str] = mapped_column(String(255))
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True, nullable=False)
    form_request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    listing_type: Mapped[str] = mapped_column(String(20))
    property_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    property_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_rent: Mapped[float | None] = mapped_column(Float, nullable=True)
    property_title: Mapped[str] = mapped_column(String(255), nullable=False, server_default="n/a")
    property_address: Mapped[str] = mapped_column(String(500), nullable=False, server_default="n/a")


class DocumentModel(Base):
    __tablename__ = "applicant_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    applicant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("applicant_applicants.id"))
    s3_key: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    document_type: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20))
    reducto_document_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ExtractedDataModel(Base):
    __tablename__ = "applicant_extracted_data"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("applicant_documents.id"), unique=True)
    extracted_content: Mapped[dict] = mapped_column(JSON)
    extraction_status: Mapped[str] = mapped_column(String(20))


class ScreeningReportModel(Base):
    __tablename__ = "applicant_screening_reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    applicant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("applicant_applicants.id"))
    risk_level: Mapped[str] = mapped_column(String(10))
    identity_verified: Mapped[bool] = mapped_column(Boolean)
    income_verified: Mapped[bool] = mapped_column(Boolean)
    dti_ratio: Mapped[float] = mapped_column(Float)
    justification: Mapped[str] = mapped_column(Text)
    listing_type: Mapped[str] = mapped_column(String(20))
    property_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    average_monthly_income: Mapped[float] = mapped_column(Float)


class EventModel(Base):
    __tablename__ = "applicant_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    applicant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("applicant_applicants.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IntakeFormRequestModel(Base):
    __tablename__ = "applicant_intake_form_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    applicant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    applicant_email: Mapped[str] = mapped_column(String(255), nullable=False)
    applicant_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    property_id: Mapped[str] = mapped_column(String(255), nullable=False)
    listing_type: Mapped[str] = mapped_column(String(20), nullable=False)
    property_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    property_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    property_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    property_address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SubmissionModel(Base):
    __tablename__ = "applicant_submissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    applicant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("applicant_applicants.id"), nullable=True
    )
    form_request_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    terms_accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
