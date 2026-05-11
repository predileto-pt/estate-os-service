"""FastAPI cookie helpers + `load_session` dependency.

The cookie name is a hardcoded constant (part of the BE/FE protocol contract,
not configurable — see spec §11).
"""

from __future__ import annotations

from fastapi import Request, Response

from sessions.application.ports.cookie_signer import CookieSigner
from sessions.application.ports.session_repository import SessionRepository
from sessions.domain.exceptions import (
    SessionDomainError,
    SessionNotFound,
    SessionRevoked,
)
from sessions.domain.models.session import Session

SESSION_COOKIE_NAME = "predileto_session"


def read_cookie(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAME)


def set_cookie(
    response: Response,
    value: str,
    *,
    domain: str,
    secure: bool,
    max_age_seconds: int,
) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=value,
        max_age=max_age_seconds,
        path="/",
        domain=domain or None,
        secure=secure,
        httponly=True,
        samesite="lax",
    )


def _get_sessions_container(request: Request):
    container = getattr(request.app.state, "sessions_container", None)
    if container is None:
        raise RuntimeError("app.state.sessions_container is not initialised")
    return container


async def load_session(request: Request) -> Session:
    """Read + verify the cookie and load the session row.

    Raises domain exceptions; the exception handler in
    `sessions.adapters.api.exception_handlers` maps them to HTTP responses.
    """
    container = _get_sessions_container(request)
    signer: CookieSigner = container.cookie_signer
    repo: SessionRepository = container.repo

    cookie_value = read_cookie(request)
    if cookie_value is None:
        raise SessionNotFound("cookie missing")

    session_id = signer.verify(cookie_value)  # may raise CookieMalformed / CookieSignatureInvalid
    session = await repo.get_by_id(session_id)
    if session is None:
        raise SessionNotFound(str(session_id))
    if session.revoked:
        raise SessionRevoked(str(session_id))
    return session


# Re-exported for typing convenience.
__all__ = [
    "SESSION_COOKIE_NAME",
    "load_session",
    "read_cookie",
    "set_cookie",
    "SessionDomainError",
]
