from abc import ABC, abstractmethod
from uuid import UUID

from organizations.domain.models.invitation import Invitation


class InvitationRepository(ABC):
    @abstractmethod
    async def get_by_id(self, invitation_id: UUID) -> Invitation | None: ...

    @abstractmethod
    async def get_pending_by_email(self, email: str) -> Invitation | None: ...

    @abstractmethod
    async def get_pending_by_email_and_organization(
        self, email: str, organization_id: UUID
    ) -> Invitation | None: ...

    @abstractmethod
    async def list_by_organization(self, organization_id: UUID) -> list[Invitation]: ...

    @abstractmethod
    async def save(self, invitation: Invitation) -> Invitation: ...

    @abstractmethod
    async def update(self, invitation: Invitation) -> Invitation: ...
