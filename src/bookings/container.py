from bookings.application.ports.notification import NotificationSender
from bookings.application.ports.repositories.applicant_repository import (
    BookingApplicantRepository,
)
from bookings.application.ports.repositories.booking_repository import BookingRepository
from bookings.application.ports.repositories.slot_repository import SlotRepository
from bookings.application.services.applicant_service import ApplicantService
from bookings.application.services.booking_service import BookingService
from bookings.application.services.slot_service import SlotService


class Container:
    def __init__(
        self,
        slot_repo: SlotRepository,
        booking_repo: BookingRepository,
        applicant_repo: BookingApplicantRepository,
        notifier: NotificationSender,
        booking_secret: str,
        booking_link_url: str,
    ) -> None:
        self.slot_service = SlotService(slot_repo, booking_repo, notifier)
        self.booking_service = BookingService(booking_repo, slot_repo, notifier)
        self.applicant_service = ApplicantService(applicant_repo)
        self.booking_secret = booking_secret
        self.booking_link_url = booking_link_url
