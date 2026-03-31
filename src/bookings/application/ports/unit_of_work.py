from bookings.application.ports.repositories.applicant_repository import BookingApplicantRepository
from bookings.application.ports.repositories.booking_repository import BookingRepository
from bookings.application.ports.repositories.slot_repository import SlotRepository
from shared.ports.unit_of_work import UnitOfWork


class BookingUnitOfWork(UnitOfWork):
    """Unit of Work for the booking_management bounded context.

    Exposes the three repositories as attributes; implementations must
    initialise them in ``__aenter__``.
    """

    slots: SlotRepository
    bookings: BookingRepository
    applicants: BookingApplicantRepository
