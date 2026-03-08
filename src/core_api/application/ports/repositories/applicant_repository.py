from abc import ABC, abstractmethod
from uuid import UUID

from core_api.domain.models.applicant import Applicant


class ApplicantRepository(ABC):
    @abstractmethod
    async def get_by_id(self, applicant_id: UUID) -> Applicant | None: ...

    @abstractmethod
    async def get_by_form_request_id(self, form_request_id: UUID) -> Applicant | None: ...

    @abstractmethod
    async def save(self, applicant: Applicant) -> Applicant: ...

    @abstractmethod
    async def update(self, applicant: Applicant) -> Applicant: ...
