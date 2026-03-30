from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CreateSlotRequest(BaseModel):
    property_id: UUID
    organization_id: UUID
    start_time: datetime
    end_time: datetime


class CreateBookingRequest(BaseModel):
    slot_id: UUID
    notes: str = ""


class CreateBookingInvitationRequest(BaseModel):
    applicant_id: UUID
    property_id: UUID
    organization_id: UUID
    email: str


class SlotResponse(BaseModel):
    id: str
    property_id: str
    agent_user_id: str
    organization_id: str
    start_time: datetime
    end_time: datetime
    status: str
    created_at: datetime
    updated_at: datetime


class BookingResponse(BaseModel):
    id: str
    slot_id: str
    applicant_id: str
    property_id: str
    organization_id: str
    status: str
    notes: str
    created_at: datetime
    updated_at: datetime


class PaginatedSlotsResponse(BaseModel):
    slots: list[SlotResponse]
    total: int


class PaginatedBookingsResponse(BaseModel):
    bookings: list[BookingResponse]
    total: int


class BookingInvitationResponse(BaseModel):
    token: str
    url: str
    expires_at: datetime
