"""Adapter for `listings.application.ports.GetAgencyContact`.

Composition adapter — bridges the listings port to the existing
`OrganizationRepository` (organizations context) and `UserRepository`
(identity context) without introducing a cross-domain import on either
side: listings depends on `GetAgencyContact` only, and this adapter
lives outside the listings package.

Spec: `2026-05-listings-agency-contact`.

Contact source (post org-level email/phone columns):
  1. `Organization.email` / `Organization.phone` win when set.
  2. Fall back to the creating `User.email` / `User.phone` for orgs
     that haven't filled in their own contact yet.
The user-fallback exists for back-compat with pre-fields orgs; once
agency onboarding mandates org-level contact, the fallback can be
deleted.
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


def _format_phone(country_code: str, number: str) -> str:
    return f"{country_code} {number}".strip()


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

        email: str | None = org.email
        phone: str | None = (
            _format_phone(org.phone.country_code, org.phone.number)
            if org.phone is not None
            else None
        )

        # Only fetch the creating user when at least one field still
        # needs a fallback — avoids a wasted DB hit for fully-populated
        # orgs.
        if email is None or phone is None:
            user = await self._user_repo.get_by_id(org.created_by)
            if user is not None:
                if email is None:
                    email = user.email
                if phone is None and user.phone is not None:
                    phone = _format_phone(user.phone.country_code, user.phone.number)

        return AgencyContact(name=org.name, email=email, phone=phone)
