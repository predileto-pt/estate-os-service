"""GET /auth/me.

Mounted under both `/api/v1/admin` and `/api/v1/portal` in main.py.
The handler is prefix-agnostic — it reads `request.state.user` and
`request.state.memberships` set by `IdentityMiddleware` and shapes the
response.

Admin-prefix mount naturally 403s for a user with no memberships via the
middleware rule. Portal-prefix mount returns `memberships: []` for pure
portal users. No DB calls, no use case (Q2 = 2.a).
"""

from fastapi import APIRouter, Request

from identity.adapters.api.schemas import MeResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Return the current user with their memberships",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Admin access required (no memberships)"},
    },
)
async def me(request: Request):
    user = request.state.user
    memberships = request.state.memberships

    return {
        "user": {
            "id": str(user.id),
            "supabase_user_id": user.supabase_user_id,
            "email": user.email,
            "name": user.name,
            "phone": (
                {"country_code": user.phone.country_code, "number": user.phone.number}
                if user.phone
                else None
            ),
            "created_at": str(user.created_at),
            "updated_at": str(user.updated_at),
        },
        "memberships": [
            {
                "organization_id": str(m.organization_id),
                "role": m.role.value if hasattr(m.role, "value") else str(m.role),
                "organization_name": getattr(m, "organization_name", None),
                "created_at": str(m.created_at),
            }
            for m in memberships
        ],
    }
