from abc import ABC, abstractmethod
from uuid import UUID


class IntakeFormRequestRepository(ABC):
    @abstractmethod
    async def get_by_id(self, request_id: UUID) -> dict | None: ...

    @abstractmethod
    async def update_status(self, request_id: UUID, status: str) -> None: ...
