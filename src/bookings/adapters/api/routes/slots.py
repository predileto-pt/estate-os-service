from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from bookings.application.dtos import (
    CreateSlotRequest,
    PaginatedSlotsResponse,
    SlotResponse,
)
from bookings.domain.exceptions import ForbiddenError, SlotNotFoundError
from bookings.domain.models.slot import CreateSlotParams
from shared.api.dependencies import get_supabase_user_id

logger = structlog.get_logger()

router = APIRouter(prefix="/slots", tags=["booking-slots"])


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


async def _verify_property_ownership(
    request: Request, property_id: UUID, organization_id: UUID
) -> None:
    get_prop_uc = request.app.state.property_container.get_property
    try:
        prop = await get_prop_uc.execute(property_id=property_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Property not found")
    if str(prop.organization_id) != str(organization_id):
        raise HTTPException(status_code=403, detail="Property does not belong to this organization")


@router.post("", response_model=SlotResponse, status_code=201)
async def create_slot(
    body: CreateSlotRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> SlotResponse:
    await _verify_property_ownership(request, body.property_id, body.organization_id)

    container = request.app.state.booking_container
    try:
        params = CreateSlotParams(
            property_id=str(body.property_id),
            agent_user_id=supabase_user_id,
            organization_id=str(body.organization_id),
            start_time=body.start_time,
            end_time=body.end_time,
        )
        slot = await container.slot_service.create(params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _slot_response(slot)


@router.get("", response_model=PaginatedSlotsResponse)
async def list_slots(
    request: Request,
    organization_id: UUID = Query(...),
    property_id: UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> PaginatedSlotsResponse:
    container = request.app.state.booking_container
    if property_id:
        slots, total = await container.slot_service.list_by_property(
            str(property_id), str(organization_id), limit, offset
        )
    else:
        slots, total = await container.slot_service.list_by_agent(
            supabase_user_id, str(organization_id), limit, offset
        )
    return PaginatedSlotsResponse(
        slots=[_slot_response(s) for s in slots],
        total=total,
    )


@router.get("/{slot_id}", response_model=SlotResponse)
async def get_slot(
    slot_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> SlotResponse:
    container = request.app.state.booking_container
    try:
        slot = await container.slot_service.find(str(slot_id))
    except SlotNotFoundError:
        raise HTTPException(status_code=404, detail="Slot not found")
    return _slot_response(slot)


@router.delete("/{slot_id}", status_code=200)
async def cancel_slot(
    slot_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> dict:
    container = request.app.state.booking_container
    try:
        await container.slot_service.cancel(str(slot_id), supabase_user_id)
    except SlotNotFoundError:
        raise HTTPException(status_code=404, detail="Slot not found")
    except ForbiddenError:
        raise HTTPException(status_code=403, detail="Slot does not belong to this agent")
    return {}
