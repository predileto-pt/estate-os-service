from uuid import UUID

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from customers.domain.models.membership import Membership
from customers.domain.models.user import User

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
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def assert_org_member(
    request: Request,
    supabase_user_id: str,
    organization_id: UUID,
) -> tuple[User, Membership]:
    """Resolve the caller to (user, membership) in the given organization.

    Route-level authorization helper: confirms the authenticated Supabase
    user has a domain `User` record and an active `Membership` in
    `organization_id`. Raises 401 if no domain user, 403 if no membership.

    Use this from routes where `organization_id` is sourced from the request
    body or form. For routes where it's a path/query param, prefer
    `require_org_member` which composes this as a FastAPI dependency.
    """
    customer_container = request.app.state.container
    user = await customer_container.user_repo.get_by_supabase_id(supabase_user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    membership = await customer_container.membership_repo.get_by_user_and_organization(
        user_id=user.id, organization_id=organization_id
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this organization")

    return user, membership


async def require_org_member(
    organization_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> tuple[User, Membership]:
    """FastAPI dependency that enforces org membership on a route.

    Picks `organization_id` off the request's path/query params and
    delegates to `assert_org_member`. Use as
    `_member: tuple[User, Membership] = Depends(require_org_member)` on
    any admin route that takes `organization_id` as a query param.
    """
    return await assert_org_member(request, supabase_user_id, organization_id)
