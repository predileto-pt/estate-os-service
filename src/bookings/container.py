from bookings.application.ports.notification import NotificationSender
from bookings.application.ports.unit_of_work import BookingUnitOfWork
from bookings.application.services.applicant_service import ApplicantService
from bookings.application.services.booking_service import BookingService
from bookings.application.services.slot_service import SlotService


class Container:
    def __init__(
        self,
        uow: BookingUnitOfWork,
        notifier: NotificationSender,
        booking_secret: str,
        booking_link_url: str,
    ) -> None:
        self.slot_service = SlotService(uow, notifier)
        self.booking_service = BookingService(uow, notifier)
        self.applicant_service = ApplicantService(uow)
        self.booking_secret = booking_secret
        self.booking_link_url = booking_link_url
