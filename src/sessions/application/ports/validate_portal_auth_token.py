"""ValidatePortalAuthToken port — verifies a portal-Supabase JWT."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class ValidatedPortalIdentity:
    user_id: UUID
    email: str | None


class ValidatePortalAuthToken(Protocol):
    async def execute(self, auth_token: str) -> ValidatedPortalIdentity:
        """Verify the portal Supabase JWT.

        Raises `PortalAuthTokenInvalid` on any verification failure.
        """
        ...
