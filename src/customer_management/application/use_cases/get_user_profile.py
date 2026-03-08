from customer_management.application.ports.repositories.company_repository import CompanyRepository
from customer_management.application.ports.repositories.user_repository import UserRepository
from customer_management.domain.exceptions import UserNotFoundError
from customer_management.domain.models.company import Company
from customer_management.domain.models.user import User


class GetUserProfile:
    def __init__(
        self,
        user_repo: UserRepository,
        company_repo: CompanyRepository,
    ) -> None:
        self.user_repo = user_repo
        self.company_repo = company_repo

    async def execute(self, *, supabase_user_id: str) -> tuple[User, Company | None]:
        user = await self.user_repo.get_by_supabase_id(supabase_user_id)
        if not user:
            raise UserNotFoundError(supabase_user_id)

        company = await self.company_repo.get_by_id(user.company_id)
        return user, company
