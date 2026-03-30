from abc import ABC, abstractmethod
from uuid import UUID

from screening.domain.models import DomainEvent


class EventRepository(ABC):
    @abstractmethod
    async def save(self, event: DomainEvent) -> DomainEvent: ...

    @abstractmethod
    async def get_by_applicant_id(self, applicant_id: UUID) -> list[DomainEvent]: ...
