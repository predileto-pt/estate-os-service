"""Portal Supabase JWT validator — uses the shared decode helper with portal creds."""

from __future__ import annotations

from uuid import UUID

import jwt

from sessions.application.ports.validate_portal_auth_token import (
    ValidatedPortalIdentity,
    ValidatePortalAuthToken,
)
from sessions.domain.exceptions import PortalAuthTokenInvalid
from shared.auth.supabase import decode_supabase_token


class SupabasePortalTokenValidator(ValidatePortalAuthToken):
    def __init__(self, *, supabase_url: str, jwt_secret: str, audience: str) -> None:
        self._supabase_url = supabase_url
        self._jwt_secret = jwt_secret
        self._audience = audience

    async def execute(self, auth_token: str) -> ValidatedPortalIdentity:
        try:
            payload = await decode_supabase_token(
                auth_token,
                supabase_url=self._supabase_url,
                jwt_secret=self._jwt_secret,
                audience=self._audience,
            )
        except jwt.InvalidTokenError as e:
            raise PortalAuthTokenInvalid(str(e)) from e

        sub = payload.get("sub")
        if not sub:
            raise PortalAuthTokenInvalid("token missing `sub` claim")
        try:
            user_id = UUID(sub)
        except (ValueError, TypeError) as e:
            raise PortalAuthTokenInvalid(f"invalid sub claim: {sub!r}") from e
        return ValidatedPortalIdentity(user_id=user_id, email=payload.get("email"))
