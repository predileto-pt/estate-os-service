from abc import ABC, abstractmethod
from uuid import UUID

from customer_management.domain.models.portal_user import PortalUser


class PortalUserRepository(ABC):
    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> PortalUser | None: ...

    @abstractmethod
    async def get_by_supabase_id(self, supabase_user_id: str) -> PortalUser | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> PortalUser | None: ...

    @abstractmethod
    async def save(self, user: PortalUser) -> PortalUser: ...
