from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from identity.domain.models.user import User
from organizations.domain.models.membership import Membership

bearer_scheme = HTTPBearer(auto_error=False)


async def get_supabase_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    user_id = getattr(request.state, "supabase_user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


async def get_current_user(request: Request) -> User:
    """Return the `User` attached to the request by `IdentityMiddleware`.

    Middleware resolves `request.state.user` from the Supabase `sub` before
    the route handler runs. This dependency is a thin getter with a 401
    fallback for paths where the middleware didn't populate state
    (registration paths, where the handler hasn't created the user yet).
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def assert_org_member(
    request: Request,
    supabase_user_id: str,
    organization_id: UUID,
) -> tuple[User, Membership]:
    """Body-param variant of `require_org_member`.

    For POST / PATCH routes that receive `organization_id` in the request
    body (not path/query), call this explicitly from the handler. Same
    behaviour as `require_org_member`: reads `request.state.{user, memberships}`
    populated by `IdentityMiddleware` — zero DB hits. The `supabase_user_id`
    argument is retained for backward signature compatibility; the lookup
    uses `request.state` regardless.
    """
    user = getattr(request.state, "user", None)
    memberships = getattr(request.state, "memberships", None)
    if user is None or memberships is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    for m in memberships:
        if str(m.organization_id) == str(organization_id):
            return user, m

    raise HTTPException(status_code=403, detail="Not a member of this organization")


async def require_org_member(
    organization_id: UUID,
    request: Request,
) -> tuple[User, Membership]:
    """FastAPI dependency that enforces org membership on an admin route.

    Reads from `request.state.memberships` set by `IdentityMiddleware` —
    zero DB round-trips inside the dependency (Q4 = 4.a). Returns the
    `(User, Membership)` tuple for the caller's membership in the given
    org.

    Use as `_member: tuple[User, Membership] = Depends(require_org_member)`
    on any admin route that takes `organization_id` as a path/query param.
    Raises:
      - 401 if `IdentityMiddleware` didn't populate `request.state.user`
        (e.g. the endpoint is reachable through a path the middleware
        skipped but the route still requires a known user).
      - 403 if the user has no membership in `organization_id`.
    """
    user = getattr(request.state, "user", None)
    memberships = getattr(request.state, "memberships", None)
    if user is None or memberships is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    for m in memberships:
        if str(m.organization_id) == str(organization_id):
            return user, m

    raise HTTPException(status_code=403, detail="Not a member of this organization")
