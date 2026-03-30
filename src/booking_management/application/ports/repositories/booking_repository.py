from abc import ABC, abstractmethod

from booking_management.domain.models.booking import Booking, BookingStatus


class BookingRepository(ABC):
    @abstractmethod
    async def create(self, booking: Booking) -> Booking: ...

    @abstractmethod
    async def find(self, booking_id: str) -> Booking | None: ...

    @abstractmethod
    async def find_by_slot_id(self, slot_id: str) -> Booking | None: ...

    @abstractmethod
    async def update_status(self, booking_id: str, status: BookingStatus) -> None: ...

    @abstractmethod
    async def list_by_applicant(
        self, applicant_id: str, limit: int, offset: int
    ) -> tuple[list[Booking], int]: ...

    @abstractmethod
    async def list_by_organization(
        self, organization_id: str, limit: int, offset: int
    ) -> tuple[list[Booking], int]: ...
