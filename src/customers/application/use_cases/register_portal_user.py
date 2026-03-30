from datetime import datetime, timezone
from uuid import uuid4

import structlog

from customers.application.ports.repositories.portal_user_repository import (
    PortalUserRepository,
)
from customers.domain.exceptions import PortalUserAlreadyExistsError
from customers.domain.models.portal_user import PortalUser
from customers.domain.models.value_objects import PhoneNumber

log = structlog.get_logger()


class RegisterPortalUser:
    def __init__(self, portal_user_repo: PortalUserRepository) -> None:
        self.portal_user_repo = portal_user_repo

    async def execute(
        self,
        *,
        supabase_user_id: str,
        email: str,
        name: str,
        phone: PhoneNumber | None = None,
    ) -> PortalUser:
        existing = await self.portal_user_repo.get_by_supabase_id(supabase_user_id)
        if existing:
            raise PortalUserAlreadyExistsError(email)

        now = datetime.now(timezone.utc)

        user = PortalUser(
            id=uuid4(),
            supabase_user_id=supabase_user_id,
            email=email,
            name=name,
            phone=phone,
            created_at=now,
            updated_at=now,
        )
        user = await self.portal_user_repo.save(user)

        log.info("portal_user_registered", user_id=str(user.id), email=user.email)
        return user
