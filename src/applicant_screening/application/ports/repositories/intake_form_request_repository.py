from abc import ABC, abstractmethod
from uuid import UUID

from applicant_screening.domain.models import IntakeFormRequest, IntakeFormRequestStatus


class IntakeFormRequestRepository(ABC):
    @abstractmethod
    async def save(self, request: IntakeFormRequest) -> IntakeFormRequest: ...

    @abstractmethod
    async def get_by_id(self, request_id: UUID) -> IntakeFormRequest | None: ...

    @abstractmethod
    async def list_by_organization_id(
        self, organization_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[IntakeFormRequest]: ...

    @abstractmethod
    async def update_status(self, request_id: UUID, status: IntakeFormRequestStatus) -> None: ...
