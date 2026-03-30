from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from bookings.application.booking_token import generate_booking_token
from bookings.application.dtos import (
    BookingInvitationResponse,
    BookingResponse,
    CreateBookingInvitationRequest,
    PaginatedBookingsResponse,
)
from bookings.domain.exceptions import (
    BookingNotCancellableError,
    BookingNotFoundError,
    ForbiddenError,
)
from shared.api.dependencies import get_supabase_user_id

logger = structlog.get_logger()

router = APIRouter(tags=["booking-bookings"])


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


@router.get("/bookings", response_model=PaginatedBookingsResponse)
async def list_bookings(
    request: Request,
    organization_id: UUID = Query(...),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> PaginatedBookingsResponse:
    container = request.app.state.booking_container
    bookings, total = await container.booking_service.list_by_organization(
        str(organization_id), limit, offset
    )
    return PaginatedBookingsResponse(
        bookings=[_booking_response(b) for b in bookings],
        total=total,
    )


@router.get("/bookings/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> BookingResponse:
    container = request.app.state.booking_container
    try:
        booking = await container.booking_service.find(str(booking_id))
    except BookingNotFoundError:
        raise HTTPException(status_code=404, detail="Booking not found")
    return _booking_response(booking)


@router.delete("/bookings/{booking_id}", status_code=200)
async def cancel_booking(
    booking_id: UUID,
    request: Request,
    organization_id: UUID = Query(...),
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> dict:
    container = request.app.state.booking_container
    try:
        await container.booking_service.cancel_by_agent(str(booking_id), str(organization_id))
    except BookingNotFoundError:
        raise HTTPException(status_code=404, detail="Booking not found")
    except ForbiddenError:
        raise HTTPException(status_code=403, detail="Not authorized")
    except BookingNotCancellableError:
        raise HTTPException(status_code=400, detail="Booking cannot be cancelled")
    return {}


@router.post("/booking-invitations", response_model=BookingInvitationResponse, status_code=201)
async def create_booking_invitation(
    body: CreateBookingInvitationRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> BookingInvitationResponse:
    container = request.app.state.booking_container
    token, expires_at = generate_booking_token(
        secret=container.booking_secret,
        applicant_id=str(body.applicant_id),
        property_id=str(body.property_id),
        organization_id=str(body.organization_id),
        email=body.email,
    )
    url = f"{container.booking_link_url}?token={token}"
    return BookingInvitationResponse(token=token, url=url, expires_at=expires_at)
