from datetime import datetime
from uuid import uuid4

import structlog

from bookings.application.ports.notification import NotificationSender
from bookings.application.ports.unit_of_work import BookingUnitOfWork
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
        uow: BookingUnitOfWork,
        notifier: NotificationSender,
    ) -> None:
        self._uow = uow
        self.notifier = notifier

    async def create(self, slot_id: str, applicant_id: str, notes: str = "") -> Booking:
        async with self._uow:
            # 1. Find the slot.
            slot = await self._uow.slots.find(slot_id)
            if slot is None:
                raise SlotNotFoundError(slot_id)

            if not slot.is_available():
                raise SlotNotAvailableError(slot_id)

            # 2. Atomically mark slot as booked (optimistic lock).
            booked = await self._uow.slots.mark_booked(slot_id)
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
            created = await self._uow.bookings.create(booking)

            await self._uow.commit()  # atomic: slot + booking

        # Notify after commit
        await self.notifier.booking_confirmed(created)
        logger.info("booking_created", booking_id=created.id, slot_id=slot_id)
        return created

    async def find(self, booking_id: str) -> Booking:
        async with self._uow:
            booking = await self._uow.bookings.find(booking_id)
        if booking is None:
            raise BookingNotFoundError(booking_id)
        return booking

    async def list_by_applicant(
        self, applicant_id: str, limit: int, offset: int
    ) -> tuple[list[Booking], int]:
        async with self._uow:
            return await self._uow.bookings.list_by_applicant(applicant_id, limit, offset)

    async def list_by_organization(
        self, organization_id: str, limit: int, offset: int
    ) -> tuple[list[Booking], int]:
        async with self._uow:
            return await self._uow.bookings.list_by_organization(organization_id, limit, offset)

    async def cancel_by_applicant(self, booking_id: str, applicant_id: str) -> None:
        async with self._uow:
            booking = await self._uow.bookings.find(booking_id)
            if booking is None:
                raise BookingNotFoundError(booking_id)

            if not booking.belongs_to_applicant(applicant_id):
                raise ForbiddenError("Booking does not belong to this applicant")

            if not booking.is_confirmed():
                raise BookingNotCancellableError(booking_id)

            await self._uow.bookings.update_status(booking_id, BookingStatus.CANCELLED_BY_APPLICANT)
            await self._uow.slots.mark_available(booking.slot_id)

            await self._uow.commit()

        await self.notifier.booking_cancelled(booking)
        logger.info("booking_cancelled_by_applicant", booking_id=booking_id)

    async def cancel_by_agent(self, booking_id: str, organization_id: str) -> None:
        async with self._uow:
            booking = await self._uow.bookings.find(booking_id)
            if booking is None:
                raise BookingNotFoundError(booking_id)

            if not booking.belongs_to_organization(organization_id):
                raise ForbiddenError("Booking does not belong to this organization")

            if not booking.is_confirmed():
                raise BookingNotCancellableError(booking_id)

            await self._uow.bookings.update_status(booking_id, BookingStatus.CANCELLED_BY_AGENT)
            await self._uow.slots.mark_available(booking.slot_id)

            await self._uow.commit()

        await self.notifier.booking_cancelled(booking)
        logger.info("booking_cancelled_by_agent", booking_id=booking_id)
