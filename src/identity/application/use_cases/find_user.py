"""User lookup — two methods, two callers.

- `by_id(id)` is bound as the `UserLookupById` callable Protocol and
  consumed by `organizations` (cross-context boundary).
- `by_supabase_id(supabase_user_id)` is called directly by the
  `IdentityMiddleware` — shared infrastructure is not a bounded context,
  so it may call use-case methods without a Protocol layer (Q2 = 2.b).
"""

from uuid import UUID

from identity.application.ports.repositories.user_repository import UserRepository
from identity.domain.models.user import User


class FindUser:
    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def by_id(self, id: UUID) -> User | None:
        return await self.user_repo.get_by_id(id)

    async def by_supabase_id(self, supabase_user_id: str) -> User | None:
        return await self.user_repo.get_by_supabase_id(supabase_user_id)
