from uuid import UUID

from core_api.application.ports.repositories.company_repository import CompanyRepository
from core_api.domain.models.company import Company


class InMemoryCompanyRepository(CompanyRepository):
    def __init__(self) -> None:
        self._companies: dict[UUID, Company] = {}

    async def get_by_id(self, company_id: UUID) -> Company | None:
        return self._companies.get(company_id)

    async def save(self, company: Company) -> Company:
        self._companies[company.id] = company
        return company

    async def update(self, company: Company) -> Company:
        self._companies[company.id] = company
        return company
