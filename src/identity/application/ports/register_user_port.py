"""Cross-context write port: register a new user.

Consumed by `organizations.RegisterAdminAccount` to create the User row
before composing the org/membership/subscription part of admin signup.

Callable Protocol — bound at container-construction time to
`RegisterUser.execute`. Idempotent: duplicate `supabase_user_id` returns
the existing User rather than raising. See Q1 = 1.c and Q3 = 3.a.
"""

from typing import Protocol

from identity.domain.models.user import User
from identity.domain.value_objects import PhoneNumber


class RegisterUserPort(Protocol):
    async def __call__(
        self,
        *,
        supabase_user_id: str,
        email: str,
        name: str,
        phone: PhoneNumber | None = None,
        google_metadata: dict | None = None,
    ) -> User: ...
