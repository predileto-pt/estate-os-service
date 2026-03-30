from abc import ABC, abstractmethod

from bookings.domain.models.booking import Booking
from bookings.domain.models.slot import Slot


class NotificationSender(ABC):
    @abstractmethod
    async def booking_confirmed(self, booking: Booking) -> None: ...

    @abstractmethod
    async def booking_cancelled(self, booking: Booking) -> None: ...

    @abstractmethod
    async def slot_cancelled(self, slot: Slot, booking: Booking | None) -> None: ...
