from uuid import UUID

from core_api.application.ports.repositories.applicant_repository import ApplicantRepository
from core_api.domain.models.applicant import Applicant


class InMemoryApplicantRepository(ApplicantRepository):
    def __init__(self) -> None:
        self._applicants: dict[UUID, Applicant] = {}

    async def get_by_id(self, applicant_id: UUID) -> Applicant | None:
        return self._applicants.get(applicant_id)

    async def get_by_form_request_id(self, form_request_id: UUID) -> Applicant | None:
        for applicant in self._applicants.values():
            if applicant.form_request_id == form_request_id:
                return applicant
        return None

    async def save(self, applicant: Applicant) -> Applicant:
        self._applicants[applicant.id] = applicant
        return applicant

    async def update(self, applicant: Applicant) -> Applicant:
        self._applicants[applicant.id] = applicant
        return applicant
