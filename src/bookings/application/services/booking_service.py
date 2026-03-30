from datetime import datetime
from uuid import uuid4

import structlog

from bookings.application.ports.notification import NotificationSender
from bookings.application.ports.repositories.booking_repository import BookingRepository
from bookings.application.ports.repositories.slot_repository import SlotRepository
from bookings.domain.exceptions import (
    BookingNotCancellableError,
    BookingNotFoundError,
    ForbiddenError,
    SlotNotAvailableError,
    SlotNotFoundError,
)
from bookings.domain.models.booking import Booking, BookingStatus

logger = structlog.get_logger()


class BookingService:
    def __init__(
        self,
        booking_repo: BookingRepository,
        slot_repo: SlotRepository,
        notifier: NotificationSender,
    ) -> None:
        self.booking_repo = booking_repo
        self.slot_repo = slot_repo
        self.notifier = notifier

    async def create(self, slot_id: str, applicant_id: str, notes: str = "") -> Booking:
        # 1. Find the slot.
        slot = await self.slot_repo.find(slot_id)
        if slot is None:
            raise SlotNotFoundError(slot_id)

        if not slot.is_available():
            raise SlotNotAvailableError(slot_id)

        # 2. Atomically mark slot as booked (optimistic lock).
        booked = await self.slot_repo.mark_booked(slot_id)
        if not booked:
            raise SlotNotAvailableError(slot_id)

        # 3. Persist the booking.
        now = datetime.now()
        booking = Booking(
            id=str(uuid4()),
            slot_id=slot_id,
            applicant_id=applicant_id,
            property_id=slot.property_id,
            organization_id=slot.organization_id,
            status=BookingStatus.CONFIRMED,
            notes=notes,
            created_at=now,
            updated_at=now,
        )

        try:
            created = await self.booking_repo.create(booking)
        except Exception:
            # Rollback: release the slot if booking insert fails.
            await self.slot_repo.mark_available(slot_id)
            raise

        await self.notifier.booking_confirmed(created)
        logger.info("booking_created", booking_id=created.id, slot_id=slot_id)
        return created

    async def find(self, booking_id: str) -> Booking:
        booking = await self.booking_repo.find(booking_id)
        if booking is None:
            raise BookingNotFoundError(booking_id)
        return booking

    async def list_by_applicant(
        self, applicant_id: str, limit: int, offset: int
    ) -> tuple[list[Booking], int]:
        return await self.booking_repo.list_by_applicant(applicant_id, limit, offset)

    async def list_by_organization(
        self, organization_id: str, limit: int, offset: int
    ) -> tuple[list[Booking], int]:
        return await self.booking_repo.list_by_organization(organization_id, limit, offset)

    async def cancel_by_applicant(self, booking_id: str, applicant_id: str) -> None:
        booking = await self.find(booking_id)

        if not booking.belongs_to_applicant(applicant_id):
            raise ForbiddenError("Booking does not belong to this applicant")

        if not booking.is_confirmed():
            raise BookingNotCancellableError(booking_id)

        await self.booking_repo.update_status(booking_id, BookingStatus.CANCELLED_BY_APPLICANT)
        await self.slot_repo.mark_available(booking.slot_id)
        await self.notifier.booking_cancelled(booking)
        logger.info("booking_cancelled_by_applicant", booking_id=booking_id)

    async def cancel_by_agent(self, booking_id: str, organization_id: str) -> None:
        booking = await self.find(booking_id)

        if not booking.belongs_to_organization(organization_id):
            raise ForbiddenError("Booking does not belong to this organization")

        if not booking.is_confirmed():
            raise BookingNotCancellableError(booking_id)

        await self.booking_repo.update_status(booking_id, BookingStatus.CANCELLED_BY_AGENT)
        await self.slot_repo.mark_available(booking.slot_id)
        await self.notifier.booking_cancelled(booking)
        logger.info("booking_cancelled_by_agent", booking_id=booking_id)
