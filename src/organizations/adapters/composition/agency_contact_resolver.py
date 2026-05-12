"""Adapter for `listings.application.ports.GetAgencyContact`.

Composition adapter — bridges the listings port to the existing
`OrganizationRepository` (organizations context) and `UserRepository`
(identity context) without introducing a cross-domain import on either
side: listings depends on `GetAgencyContact` only, and this adapter
lives outside the listings package.

Spec: `2026-05-listings-agency-contact`.
"""

from __future__ import annotations

from uuid import UUID

from identity.application.ports.repositories.user_repository import UserRepository
from listings.application.ports.get_agency_contact import (
    AgencyContact,
    GetAgencyContact,
)
from organizations.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)


class AgencyContactResolver(GetAgencyContact):
    def __init__(
        self,
        *,
        organization_repo: OrganizationRepository,
        user_repo: UserRepository,
    ) -> None:
        self._org_repo = organization_repo
        self._user_repo = user_repo

    async def execute(self, organization_id: UUID) -> AgencyContact:
        org = await self._org_repo.get_by_id(organization_id)
        if org is None:
            return AgencyContact(name=None, email=None, phone=None)

        user = await self._user_repo.get_by_id(org.created_by)

        phone: str | None = None
        if user is not None and user.phone is not None:
            phone = f"{user.phone.country_code} {user.phone.number}".strip()

        return AgencyContact(
            name=org.name,
            email=user.email if user is not None else None,
            phone=phone,
        )
