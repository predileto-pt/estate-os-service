from datetime import datetime
from uuid import uuid4

import structlog

from bookings.application.ports.notification import NotificationSender
from bookings.application.ports.repositories.booking_repository import BookingRepository
from bookings.application.ports.repositories.slot_repository import SlotRepository
from bookings.domain.exceptions import ForbiddenError, SlotNotFoundError
from bookings.domain.models.booking import BookingStatus
from bookings.domain.models.slot import CreateSlotParams, Slot, SlotStatus

logger = structlog.get_logger()


class SlotService:
    def __init__(
        self,
        slot_repo: SlotRepository,
        booking_repo: BookingRepository,
        notifier: NotificationSender,
    ) -> None:
        self.slot_repo = slot_repo
        self.booking_repo = booking_repo
        self.notifier = notifier

    async def create(self, params: CreateSlotParams) -> Slot:
        now = datetime.now()
        slot = Slot(
            id=str(uuid4()),
            property_id=params.property_id,
            agent_user_id=params.agent_user_id,
            organization_id=params.organization_id,
            start_time=params.start_time,
            end_time=params.end_time,
            status=SlotStatus.AVAILABLE,
            created_at=now,
            updated_at=now,
        )
        return await self.slot_repo.create(slot)

    async def find(self, slot_id: str) -> Slot:
        slot = await self.slot_repo.find(slot_id)
        if slot is None:
            raise SlotNotFoundError(slot_id)
        return slot

    async def list_by_agent(
        self, agent_user_id: str, organization_id: str, limit: int, offset: int
    ) -> tuple[list[Slot], int]:
        return await self.slot_repo.list_by_agent(agent_user_id, organization_id, limit, offset)

    async def list_by_property(
        self, property_id: str, organization_id: str, limit: int, offset: int
    ) -> tuple[list[Slot], int]:
        return await self.slot_repo.list_by_property(property_id, organization_id, limit, offset)

    async def list_available_by_property(
        self, property_id: str, from_time: datetime, limit: int, offset: int
    ) -> tuple[list[Slot], int]:
        return await self.slot_repo.list_available_by_property(
            property_id, from_time, limit, offset
        )

    async def cancel(self, slot_id: str, agent_user_id: str) -> None:
        slot = await self.find(slot_id)

        if not slot.belongs_to_agent(agent_user_id):
            raise ForbiddenError("Slot does not belong to this agent")

        # If the slot was booked, cancel the booking first.
        booking = None
        if slot.status == SlotStatus.BOOKED:
            booking = await self.booking_repo.find_by_slot_id(slot_id)
            if booking and booking.is_confirmed():
                await self.booking_repo.update_status(booking.id, BookingStatus.CANCELLED_BY_AGENT)

        await self.slot_repo.cancel(slot_id)

        await self.notifier.slot_cancelled(slot, booking)
        logger.info("slot_cancelled", slot_id=slot_id)
