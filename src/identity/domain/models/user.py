from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from identity.domain.value_objects import PhoneNumber


@dataclass
class User:
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
