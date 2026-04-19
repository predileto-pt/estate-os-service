from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    name: str
    email: str
    phone_country_code: str | None = Field(default=None, description="E.g. +351")
    phone_number: str | None = None


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    phone_country_code: str | None = None
    phone_number: str | None = None


class PhoneResponse(BaseModel):
    country_code: str
    number: str


class UserResponse(BaseModel):
    id: str
    supabase_user_id: str
    email: str
    name: str
    phone: PhoneResponse | None = None
    created_at: str
    updated_at: str


class MembershipSummary(BaseModel):
    """Projection of a Membership + its Organization.name, as returned by
    `MembershipRepository.list_by_user_id_with_org_names` and attached to
    `request.state.memberships` by `IdentityMiddleware`.
    """

    organization_id: str
    role: str
    organization_name: str | None
    created_at: str


class MeResponse(BaseModel):
    user: UserResponse
    memberships: list[MembershipSummary]
