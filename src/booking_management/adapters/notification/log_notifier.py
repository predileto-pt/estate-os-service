import structlog

from booking_management.application.ports.notification import NotificationSender
from booking_management.domain.models.booking import Booking
from booking_management.domain.models.slot import Slot

logger = structlog.get_logger()


class LogNotifier(NotificationSender):
    async def booking_confirmed(self, booking: Booking) -> None:
        logger.info(
            "notification.booking_confirmed",
            booking_id=booking.id,
            slot_id=booking.slot_id,
            applicant_id=booking.applicant_id,
        )

    async def booking_cancelled(self, booking: Booking) -> None:
        logger.info(
            "notification.booking_cancelled",
            booking_id=booking.id,
            status=booking.status,
        )

    async def slot_cancelled(self, slot: Slot, booking: Booking | None) -> None:
        logger.info(
            "notification.slot_cancelled",
            slot_id=slot.id,
            had_booking=booking is not None,
        )
