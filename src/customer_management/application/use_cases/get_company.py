from uuid import UUID

from customer_management.application.ports.repositories.company_repository import CompanyRepository
from customer_management.application.ports.repositories.user_repository import UserRepository
from customer_management.domain.exceptions import (
    AuthorizationError,
    CompanyNotFoundError,
    UserNotFoundError,
)
from customer_management.domain.models.company import Company


class GetCompany:
    def __init__(self, company_repo: CompanyRepository, user_repo: UserRepository) -> None:
        self.company_repo = company_repo
        self.user_repo = user_repo

    async def execute(self, *, supabase_user_id: str, company_id: UUID) -> Company:
        user = await self.user_repo.get_by_supabase_id(supabase_user_id)
        if not user:
            raise UserNotFoundError(supabase_user_id)

        if user.company_id != company_id:
            raise AuthorizationError("Not authorized to access this company")

        company = await self.company_repo.get_by_id(company_id)
        if not company:
            raise CompanyNotFoundError(str(company_id))

        return company
