from abc import ABC, abstractmethod
from uuid import UUID

from screening.domain.models import ScreeningAuditEvent


class EventRepository(ABC):
    @abstractmethod
    async def save(self, event: ScreeningAuditEvent) -> ScreeningAuditEvent: ...

    @abstractmethod
    async def get_by_applicant_id(self, applicant_id: UUID) -> list[ScreeningAuditEvent]: ...
