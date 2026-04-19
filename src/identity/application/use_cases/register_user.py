"""Idempotent user registration.

Per spec Q3 = 3.a: `RegisterUser.execute` is **idempotent on
`supabase_user_id`**. A duplicate sub returns the existing User row
rather than raising. This keeps `POST /portal/auth/register` safe to
retry (network flakes, double-clicks) and — more importantly — lets
`organizations.RegisterAdminAccount` recover from a step-3 failure by
simply retrying the whole endpoint.

Callers who need the "raise on duplicate" semantics should guard at the
HTTP layer (e.g. the portal register route returns 200 on the idempotent
case; the admin register route returns 409 via the separate
duplicate-account check on memberships).
"""

from datetime import datetime, timezone
from uuid import uuid4

import structlog

from identity.application.ports.repositories.user_repository import UserRepository
from identity.domain.models.user import User
from identity.domain.value_objects import PhoneNumber

log = structlog.get_logger()


class RegisterUser:
    def __init__(self, user_repo: UserRepository) -> None:
        self.user_repo = user_repo

    async def execute(
        self,
        *,
        supabase_user_id: str,
        email: str,
        name: str,
        phone: PhoneNumber | None = None,
        google_metadata: dict | None = None,
    ) -> User:
        existing = await self.user_repo.get_by_supabase_id(supabase_user_id)
        if existing:
            log.info(
                "user_register_idempotent_hit",
                user_id=str(existing.id),
                supabase_user_id=supabase_user_id,
            )
            return existing

        now = datetime.now(timezone.utc)
        user = User(
            id=uuid4(),
            supabase_user_id=supabase_user_id,
            email=email,
            name=name,
            phone=phone,
            google_metadata=google_metadata,
            created_at=now,
            updated_at=now,
        )
        user = await self.user_repo.save(user)
        log.info("user_registered", user_id=str(user.id), email=user.email)
        return user
