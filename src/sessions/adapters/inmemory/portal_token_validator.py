"""In-memory `ValidatePortalAuthToken` for tests."""

from __future__ import annotations

from sessions.application.ports.validate_portal_auth_token import (
    ValidatedPortalIdentity,
    ValidatePortalAuthToken,
)
from sessions.domain.exceptions import PortalAuthTokenInvalid


class StubPortalTokenValidator(ValidatePortalAuthToken):
    """Maps a fixed token string → identity. Unknown tokens raise."""

    def __init__(self, mapping: dict[str, ValidatedPortalIdentity] | None = None) -> None:
        self._mapping: dict[str, ValidatedPortalIdentity] = dict(mapping or {})

    def register(self, token: str, identity: ValidatedPortalIdentity) -> None:
        self._mapping[token] = identity

    async def execute(self, auth_token: str) -> ValidatedPortalIdentity:
        try:
            return self._mapping[auth_token]
        except KeyError as e:
            raise PortalAuthTokenInvalid(f"unknown token: {auth_token!r}") from e
