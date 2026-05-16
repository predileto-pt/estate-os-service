"""Public, cookie-authed session endpoints — mounted at `/api/v1/portal/session`.

`GET /me` is the recommended single endpoint for FE bootstrap: it auto-mints
an anonymous session on the first hit (no cookie → set one) and returns the
view in one round-trip. `POST /init` is preserved as an explicit-mint surface
for middleware-mint patterns where the FE wants the cookie established by
the time the page renders.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, Response

from sessions.adapters.api.cookie import (
    SESSION_COOKIE_NAME,
    load_session,
    read_cookie,
    set_cookie,
)
from sessions.adapters.api.schemas import SessionPatchRequest, SessionView
from sessions.application.use_cases.update_session_slice import (
    FavoritesPatch,
    PrefsPatch,
    SessionPatch,
    parse_favorite_ids,
)
from sessions.domain.exceptions import (
    CookieMalformed,
    CookieSignatureInvalid,
    PortalAuthTokenInvalid,
    SessionNotFound,
    SessionRevoked,
)
from sessions.domain.models.capability import capabilities_of
from sessions.domain.models.session import Session
from sessions.domain.value_objects import CookiesConsent

router = APIRouter(prefix="/session", tags=["session"])


def _view(session: Session) -> SessionView:
    return SessionView(
        kind=session.kind.value,
        user_id=str(session.user_id) if session.user_id is not None else None,
        capabilities=[
            c.value for c in sorted(capabilities_of(session.kind.value), key=lambda x: x.value)
        ],
        prefs=dict(session.prefs),
        favorites=[str(pid) for pid in sorted(session.favorites, key=str)],
        cookies_consent=session.cookies_consent.value if session.cookies_consent else None,
    )


async def _load_session_optional(request: Request) -> Session | None:
    """Variant of `load_session` that returns None instead of raising on missing/invalid."""
    if read_cookie(request) is None:
        return None
    try:
        return await load_session(request)
    except (SessionNotFound, SessionRevoked, CookieMalformed, CookieSignatureInvalid):
        return None


@router.post(
    "/init",
    response_model=SessionView,
    summary="Mint or refresh an anonymous portal session",
)
async def init_session(request: Request, response: Response) -> SessionView:
    container = request.app.state.sessions_container
    existing = await _load_session_optional(request)
    result = await container.init_session.execute(
        existing=existing,
        debounce_seconds=container.last_seen_debounce_seconds,
    )
    if result.minted:
        cookie_value = container.cookie_signer.sign(result.session.id)
        set_cookie(
            response,
            cookie_value,
            domain=container.cookie_domain,
            secure=container.cookie_secure,
            max_age_seconds=container.cookie_max_age_seconds,
        )
    return _view(result.session)


@router.get(
    "/me",
    response_model=SessionView,
    summary="Return the current session view (auto-mints anonymous if no cookie)",
)
async def get_session_me(request: Request, response: Response) -> SessionView:
    """Return the session view. Behaviour by cookie state:

    - **No cookie**: mint a fresh anonymous session, set the cookie, return
      the view. One-call bootstrap for FE.
    - **Valid cookie**: return the existing session (debounced `last_seen_at`).
    - **Invalid cookie** (tampered/expired/orphaned row): 401 `SESSION_INVALID`.
      We don't auto-mint here because preserving the signal helps the FE
      detect tampering and tells callers to drop the bad cookie + retry.
    """
    container = request.app.state.sessions_container
    cookie_value = read_cookie(request)

    if cookie_value is not None:
        # Cookie present — `load_session` enforces signature + row. On any
        # failure it raises a domain exception, caught by the registered
        # handler and returned as 401 SESSION_INVALID.
        session = await load_session(request)
        refreshed = await container.get_session_view.execute(
            session,
            debounce_seconds=container.last_seen_debounce_seconds,
        )
        return _view(refreshed)

    # No cookie at all — mint a fresh anonymous session.
    result = await container.init_session.execute(
        existing=None,
        debounce_seconds=container.last_seen_debounce_seconds,
    )
    cookie_value = container.cookie_signer.sign(result.session.id)
    set_cookie(
        response,
        cookie_value,
        domain=container.cookie_domain,
        secure=container.cookie_secure,
        max_age_seconds=container.cookie_max_age_seconds,
    )
    return _view(result.session)


@router.patch(
    "/me",
    response_model=SessionView,
    summary="Apply slice writes (favorites / prefs)",
)
async def patch_session_me(
    request: Request,
    body: SessionPatchRequest,
    session: Session = Depends(load_session),
) -> SessionView:
    container = request.app.state.sessions_container
    favorites_patch = None
    if body.favorites is not None:
        favorites_patch = FavoritesPatch(
            add=parse_favorite_ids(body.favorites.add),
            remove=parse_favorite_ids(body.favorites.remove),
        )
    prefs_patch = PrefsPatch(merge=body.prefs.merge) if body.prefs is not None else None
    cookies_consent = (
        CookiesConsent(body.cookies_consent) if body.cookies_consent is not None else None
    )
    patch = SessionPatch(
        favorites=favorites_patch,
        prefs=prefs_patch,
        cookies_consent=cookies_consent,
    )
    updated = await container.update_session_slice.execute(session, patch)
    return _view(updated)


@router.post(
    "/claim",
    response_model=SessionView,
    summary="Bind the session to a portal user (Authorization: Bearer <portal JWT>)",
)
async def claim_session(
    request: Request,
    authorization: str | None = Header(default=None),
    session: Session = Depends(load_session),
) -> SessionView:
    if not authorization or not authorization.startswith("Bearer "):
        raise PortalAuthTokenInvalid("missing Authorization: Bearer header")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise PortalAuthTokenInvalid("empty bearer token")
    container = request.app.state.sessions_container
    claimed = await container.claim_session.execute(session, token)
    return _view(claimed)


@router.post(
    "/logout",
    response_model=SessionView,
    summary="Flip the session to anonymous; clear favorites + prefs",
)
async def logout_session(
    request: Request,
    session: Session = Depends(load_session),
) -> SessionView:
    container = request.app.state.sessions_container
    cleared = await container.logout_session.execute(session)
    return _view(cleared)


# Avoid "F401 unused" — re-export for the main app wiring.
_ = SESSION_COOKIE_NAME
