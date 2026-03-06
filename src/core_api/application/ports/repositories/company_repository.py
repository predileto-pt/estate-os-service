from abc import ABC, abstractmethod
from uuid import UUID

from core_api.domain.models.company import Company


class CompanyRepository(ABC):
    @abstractmethod
    async def get_by_id(self, company_id: UUID) -> Company | None: ...

    @abstractmethod
    async def save(self, company: Company) -> Company: ...

    @abstractmethod
    async def update(self, company: Company) -> Company: ...
