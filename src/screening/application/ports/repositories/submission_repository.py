from abc import ABC, abstractmethod
from uuid import UUID

from screening.domain.models import Submission


class SubmissionRepository(ABC):
    @abstractmethod
    async def save(self, submission: Submission) -> Submission: ...

    @abstractmethod
    async def get_by_id(self, submission_id: UUID) -> Submission | None: ...

    @abstractmethod
    async def get_by_applicant_id(self, applicant_id: UUID) -> Submission | None: ...

    @abstractmethod
    async def get_by_form_request_id(self, form_request_id: UUID) -> Submission | None: ...

    @abstractmethod
    async def update(self, submission: Submission) -> Submission: ...
