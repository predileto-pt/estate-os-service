"""Cross-context port: resolve an organization's display contact.

Lives in `listings/` (the consumer). The adapter lives on the
`organizations` side and resolves from `Organization` + the owning
`User(created_by)`. Spec: `2026-05-listings-agency-contact`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class AgencyContact:
    name: str | None
    email: str | None
    phone: str | None


class GetAgencyContact(Protocol):
    async def execute(self, organization_id: UUID) -> AgencyContact:
        """Return the agency display contact for an org.

        Returns `AgencyContact(None, None, None)` when the org or its
        creating user is gone — the projector still writes the row,
        just with NULL agency columns.
        """
        ...
