from abc import ABC, abstractmethod
from uuid import UUID

from screening.domain.models import Applicant


class ApplicantRepository(ABC):
    @abstractmethod
    async def save(self, applicant: Applicant) -> Applicant: ...

    @abstractmethod
    async def get_by_id(self, applicant_id: UUID) -> Applicant | None: ...

    @abstractmethod
    async def get_by_nif(self, nif: str) -> Applicant | None: ...

    @abstractmethod
    async def list_by_organization_id(self, organization_id: UUID) -> list[Applicant]: ...
