from abc import ABC, abstractmethod
from datetime import datetime

from bookings.domain.models.slot import Slot


class SlotRepository(ABC):
    @abstractmethod
    async def create(self, slot: Slot) -> Slot: ...

    @abstractmethod
    async def find(self, slot_id: str) -> Slot | None: ...

    @abstractmethod
    async def mark_booked(self, slot_id: str) -> bool:
        """Atomically mark slot as booked. Returns False if not available (optimistic lock)."""
        ...

    @abstractmethod
    async def mark_available(self, slot_id: str) -> None: ...

    @abstractmethod
    async def cancel(self, slot_id: str) -> None: ...

    @abstractmethod
    async def list_available_by_property(
        self, property_id: str, from_time: datetime, limit: int, offset: int
    ) -> tuple[list[Slot], int]: ...

    @abstractmethod
    async def list_by_agent(
        self, agent_user_id: str, organization_id: str, limit: int, offset: int
    ) -> tuple[list[Slot], int]: ...

    @abstractmethod
    async def list_by_property(
        self, property_id: str, organization_id: str, limit: int, offset: int
    ) -> tuple[list[Slot], int]: ...
