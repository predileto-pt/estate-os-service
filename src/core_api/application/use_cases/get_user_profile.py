from core_api.application.ports.repositories.company_repository import CompanyRepository
from core_api.application.ports.repositories.user_repository import UserRepository
from core_api.domain.exceptions import UserNotFoundError
from core_api.domain.models.company import Company
from core_api.domain.models.user import User


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
