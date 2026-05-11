"""Maps `sessions` domain exceptions → HTTP responses (FastAPI handlers).

Registered against the session router's FastAPI app in `shared.main`.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from sessions.domain.exceptions import (
    CookieMalformed,
    CookieSignatureInvalid,
    FavoriteLimitExceeded,
    InvalidFavoriteId,
    PortalAuthTokenInvalid,
    PrefsTooLarge,
    SessionBoundToOtherUser,
    SessionNotFound,
    SessionRevoked,
)


def _json(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=status)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SessionNotFound)
    async def _(_request: Request, exc: SessionNotFound) -> JSONResponse:  # type: ignore[unused-ignore]
        # No cookie OR cookie valid but row gone. FE recovers via POST /session/init.
        return _json("SESSION_MISSING", str(exc) or "session missing", 401)

    @app.exception_handler(SessionRevoked)
    async def _(_request: Request, exc: SessionRevoked) -> JSONResponse:  # type: ignore[unused-ignore]
        return _json("SESSION_INVALID", str(exc) or "session revoked", 401)

    @app.exception_handler(CookieMalformed)
    async def _(_request: Request, exc: CookieMalformed) -> JSONResponse:  # type: ignore[unused-ignore]
        return _json("SESSION_INVALID", str(exc) or "cookie malformed", 401)

    @app.exception_handler(CookieSignatureInvalid)
    async def _(_request: Request, exc: CookieSignatureInvalid) -> JSONResponse:  # type: ignore[unused-ignore]
        return _json("SESSION_INVALID", str(exc) or "cookie signature invalid", 401)

    @app.exception_handler(PortalAuthTokenInvalid)
    async def _(_request: Request, exc: PortalAuthTokenInvalid) -> JSONResponse:  # type: ignore[unused-ignore]
        return _json("PORTAL_AUTH_TOKEN_INVALID", str(exc) or "portal auth token invalid", 401)

    @app.exception_handler(SessionBoundToOtherUser)
    async def _(_request: Request, exc: SessionBoundToOtherUser) -> JSONResponse:  # type: ignore[unused-ignore]
        return _json("SESSION_BOUND_TO_OTHER_USER", str(exc), 409)

    @app.exception_handler(PrefsTooLarge)
    async def _(_request: Request, exc: PrefsTooLarge) -> JSONResponse:  # type: ignore[unused-ignore]
        return _json("PREFS_TOO_LARGE", str(exc), 400)

    @app.exception_handler(FavoriteLimitExceeded)
    async def _(_request: Request, exc: FavoriteLimitExceeded) -> JSONResponse:  # type: ignore[unused-ignore]
        return _json("FAVORITE_LIMIT_EXCEEDED", str(exc), 400)

    @app.exception_handler(InvalidFavoriteId)
    async def _(_request: Request, exc: InvalidFavoriteId) -> JSONResponse:  # type: ignore[unused-ignore]
        return _json("INVALID_FAVORITE_ID", str(exc), 400)
