"""Domain exceptions for the sessions bounded context.

Mapped to HTTP responses by `sessions.adapters.api.exception_handlers`.
"""


class SessionDomainError(Exception):
    """Base class for all sessions-domain errors."""


class SessionNotFound(SessionDomainError):
    """No row matches the session id carried by the cookie."""


class SessionRevoked(SessionDomainError):
    """Session row exists but has `revoked=True`."""


class CookieMalformed(SessionDomainError):
    """Cookie value cannot be parsed into (session_id, signature, key_version)."""


class CookieSignatureInvalid(SessionDomainError):
    """Cookie parses but HMAC verification fails (tamper / key rotated out)."""


class PortalAuthTokenInvalid(SessionDomainError):
    """Portal Supabase JWT failed validation."""


class SessionBoundToOtherUser(SessionDomainError):
    """Claim attempted on a session already authenticated to a different user."""


class PrefsTooLarge(SessionDomainError):
    """`prefs` JSON would exceed the configured byte cap after merge."""


class FavoriteLimitExceeded(SessionDomainError):
    """Adding a favorite would exceed the configured cap (default 500)."""


class InvalidFavoriteId(SessionDomainError):
    """A supplied favorite id is not a valid UUID."""
