import jwt
import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from shared.auth.jwks import fetch_jwks_public_key
from shared.config import settings

log = structlog.get_logger()

PUBLIC_PATHS = {
    "/api/v1/health",
    "/api/v1/admin/subscriptions/plans",
    "/api/v1/admin/properties/active",
    "/api/v1/portal/bookings",
    "/docs",
    "/openapi.json",
}

# Prefix-based public paths: any request whose path starts with one of these
# bypasses JWT auth. Used for routers mounted at public roots (e.g. listings)
# where individual path params (IDs, slugs) make exact-matching infeasible.
PUBLIC_PREFIXES = ("/api/v1/listings/",)

# Registration paths bypass the `IdentityMiddleware` User-exists + membership
# checks (Q6 = 6.a). JWT is still verified by `JWTAuthMiddleware`; the route
# handler reads `request.state.supabase_user_id` to create the User row.
REGISTRATION_PATHS = {
    "/api/v1/admin/auth/register",
    "/api/v1/portal/auth/register",
}


class JWTAuthMiddleware(BaseHTTPMiddleware):
    async def _decode_token(self, token: str) -> dict:
        """Decode JWT, trying ES256 via JWKS first, then HS256 fallback."""
        # Try ES256 with JWKS public key
        if settings.supabase_url:
            public_key = await fetch_jwks_public_key(settings.supabase_url)
            if public_key:
                try:
                    return jwt.decode(
                        token, public_key, algorithms=["ES256"], audience="authenticated"
                    )
                except jwt.InvalidTokenError:
                    if not settings.supabase_jwt_secret:
                        raise

        # Fallback to HS256 with shared secret
        return jwt.decode(
            token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated"
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES) or request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return Response(status_code=401, content="Missing or invalid authorization header")

        token = auth_header.removeprefix("Bearer ")
        try:
            payload = await self._decode_token(token)
            request.state.supabase_user_id = payload["sub"]
        except jwt.InvalidTokenError as e:
            log.warning("jwt_invalid", error=str(e))
            return Response(status_code=401, content="Invalid token")

        return await call_next(request)


class IdentityMiddleware(BaseHTTPMiddleware):
    """Derives admin-ness from memberships at request time.

    Runs after `JWTAuthMiddleware`. For every non-public, non-registration
    request:

    1. Looks up the User by `supabase_user_id` → 401 if not found.
    2. Fetches memberships (with org names, via a single JOIN query — no N+1).
    3. If path is `/api/v1/admin/*` and memberships are empty → 403.
    4. Attaches `request.state.user` and `request.state.memberships`.

    Registration paths (`REGISTRATION_PATHS`) skip steps 1-3 — the route
    handler creates the User row using the verified JWT. Public paths and
    OPTIONS requests pass through untouched.

    See spec: identity-context-split-and-membership-auth.md (Q2 = 2.b —
    shared infrastructure calls identity use-case methods directly, no
    Protocol layer; Q4 = 4.a — `require_org_member` reads this state).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if (
            path in PUBLIC_PATHS
            or path.startswith(PUBLIC_PREFIXES)
            or request.method == "OPTIONS"
        ):
            return await call_next(request)

        sub = getattr(request.state, "supabase_user_id", None)
        if not sub:
            # Shouldn't happen — JWTAuthMiddleware should have set this or
            # returned 401 earlier. Belt-and-suspenders.
            return Response(status_code=401, content="Not authenticated")

        if path in REGISTRATION_PATHS:
            # JWT is verified; route handler creates the User row.
            return await call_next(request)

        identity_container = request.app.state.identity_container
        organizations_container = request.app.state.organizations_container

        user = await identity_container.find_user.by_supabase_id(sub)
        if not user:
            log.warning("identity_middleware.user_not_found", sub=sub, path=path)
            return Response(status_code=401, content="Unknown user — registration required")
        request.state.user = user

        # Single JOIN: memberships + organization_name projection (no N+1).
        memberships = await organizations_container.membership_repo.list_by_user_id_with_org_names(
            user.id
        )
        request.state.memberships = memberships

        if path.startswith("/api/v1/admin/") and not memberships:
            log.info(
                "identity_middleware.admin_access_denied",
                user_id=str(user.id),
                path=path,
            )
            return Response(
                status_code=403,
                content="This account does not have admin access",
            )

        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        log.info("request_started", method=request.method, path=request.url.path)
        response = await call_next(request)
        log.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        return response
