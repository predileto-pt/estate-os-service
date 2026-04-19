from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from organizations.domain.models.value_objects import PhoneNumber


@dataclass
class User:
    """Organizations-internal mirror of `identity.User`.

    Same shape as `identity.domain.models.user.User` (no `organization_id`
    — that field is dropped in the identity-split Alembic migration).
    Org-side use cases (invite_member, list_members, etc.) look up users
    by email/id through the org's own `UserRepository` port — keeps the
    `grep "from identity"` acceptance criterion tight (no imports of
    identity's domain class into organizations' business code).
    """

    id: UUID
    supabase_user_id: str  # maps to auth.users.id
    email: str
    name: str
    phone: PhoneNumber | None
    google_metadata: dict | None
    created_at: datetime
    updated_at: datetime

    _SENTINEL = object()

    def update_profile(
        self, *, name: str | None = None, phone: PhoneNumber | None | object = _SENTINEL
    ) -> None:
        if name is not None:
            self.name = name
        if phone is not User._SENTINEL:
            self.phone = phone  # type: ignore[assignment]
        self.updated_at = datetime.now(timezone.utc)
