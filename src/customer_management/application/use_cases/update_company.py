from uuid import UUID

from customer_management.application.ports.repositories.company_repository import CompanyRepository
from customer_management.domain.exceptions import AuthorizationError, CompanyNotFoundError
from customer_management.domain.models.company import Company


class UpdateCompany:
    def __init__(self, company_repo: CompanyRepository) -> None:
        self.company_repo = company_repo

    async def execute(
        self,
        *,
        company_id: UUID,
        requesting_user_company_id: UUID,
        name: str | None = None,
        nif: str | None = None,
        address: str | None = None,
    ) -> Company:
        if company_id != requesting_user_company_id:
            raise AuthorizationError("Cannot update another company")

        company = await self.company_repo.get_by_id(company_id)
        if not company:
            raise CompanyNotFoundError(str(company_id))

        company.update(name=name, nif=nif, address=address)

        return await self.company_repo.update(company)
