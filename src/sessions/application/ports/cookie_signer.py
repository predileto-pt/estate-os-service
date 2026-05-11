"""CookieSigner port — abstract HMAC sign + verify interface."""

from __future__ import annotations

from typing import Protocol

from sessions.domain.value_objects import SessionId


class CookieSigner(Protocol):
    def sign(self, session_id: SessionId) -> str:
        """Return the cookie value (base64url(id).base64url(sig).N)."""
        ...

    def verify(self, cookie_value: str) -> SessionId:
        """Parse + verify the cookie; return the SessionId.

        Raises `CookieMalformed` if the value can't be parsed,
        `CookieSignatureInvalid` if HMAC fails or key version is unknown.
        """
        ...
