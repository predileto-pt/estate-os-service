from datetime import datetime, timezone
from uuid import UUID

import jwt as pyjwt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from booking_management.application.booking_token import validate_booking_token
from booking_management.application.dtos import (
    BookingResponse,
    CreateBookingRequest,
    PaginatedBookingsResponse,
    PaginatedSlotsResponse,
    SlotResponse,
)
from booking_management.domain.exceptions import SlotNotAvailableError, SlotNotFoundError
from shared.api.dependencies import get_supabase_user_id

logger = structlog.get_logger()

router = APIRouter(tags=["portal-bookings"])


def _slot_response(slot) -> SlotResponse:
    return SlotResponse(
        id=slot.id,
        property_id=slot.property_id,
        agent_user_id=slot.agent_user_id,
        organization_id=slot.organization_id,
        start_time=slot.start_time,
        end_time=slot.end_time,
        status=slot.status.value,
        created_at=slot.created_at,
        updated_at=slot.updated_at,
    )


def _booking_response(booking) -> BookingResponse:
    return BookingResponse(
        id=booking.id,
        slot_id=booking.slot_id,
        applicant_id=booking.applicant_id,
        property_id=booking.property_id,
        organization_id=booking.organization_id,
        status=booking.status.value,
        notes=booking.notes,
        created_at=booking.created_at,
        updated_at=booking.updated_at,
    )


@router.get("/properties/{property_id}/slots", response_model=PaginatedSlotsResponse)
async def list_available_slots(
    property_id: UUID,
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> PaginatedSlotsResponse:
    container = request.app.state.booking_container
    from_time = datetime.now(timezone.utc)
    slots, total = await container.slot_service.list_available_by_property(
        str(property_id), from_time, limit, offset
    )
    return PaginatedSlotsResponse(
        slots=[_slot_response(s) for s in slots],
        total=total,
    )


@router.post("/bookings", response_model=BookingResponse, status_code=201)
async def create_booking(
    body: CreateBookingRequest,
    request: Request,
) -> BookingResponse:
    """Create a booking using a booking invitation token (not Supabase JWT)."""
    container = request.app.state.booking_container

    # Extract and validate booking token from Authorization header.
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing booking token")

    token_str = auth_header.removeprefix("Bearer ")
    try:
        claims = validate_booking_token(container.booking_secret, token_str)
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired booking token")

    try:
        booking = await container.booking_service.create(
            slot_id=str(body.slot_id),
            applicant_id=claims.applicant_id,
            notes=body.notes,
        )
    except SlotNotFoundError:
        raise HTTPException(status_code=404, detail="Slot not found")
    except SlotNotAvailableError:
        raise HTTPException(status_code=409, detail="Slot is no longer available")

    return _booking_response(booking)


@router.get("/bookings/status", response_model=PaginatedBookingsResponse)
async def list_applicant_bookings(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> PaginatedBookingsResponse:
    container = request.app.state.booking_container

    # Resolve applicant from supabase_user_id.
    applicant = await container.applicant_service.find_by_supabase_user_id(supabase_user_id)
    if applicant is None:
        return PaginatedBookingsResponse(bookings=[], total=0)

    bookings, total = await container.booking_service.list_by_applicant(applicant.id, limit, offset)
    return PaginatedBookingsResponse(
        bookings=[_booking_response(b) for b in bookings],
        total=total,
    )
