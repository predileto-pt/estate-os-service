from uuid import UUID

from organizations.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from organizations.domain.models.organization import Organization


class InMemoryOrganizationRepository(OrganizationRepository):
    def __init__(self) -> None:
        self._organizations: dict[UUID, Organization] = {}

    async def get_by_id(self, organization_id: UUID) -> Organization | None:
        return self._organizations.get(organization_id)

    async def save(self, organization: Organization) -> Organization:
        self._organizations[organization.id] = organization
        return organization

    async def update(self, organization: Organization) -> Organization:
        self._organizations[organization.id] = organization
        return organization
