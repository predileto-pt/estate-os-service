from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from customer_management.domain.models.value_objects import PhoneNumber


@dataclass
class PortalUser:
    id: UUID
    supabase_user_id: str
    email: str
    name: str
    phone: PhoneNumber | None
    created_at: datetime
    updated_at: datetime

    _SENTINEL = object()

    def update_profile(
        self, *, name: str | None = None, phone: PhoneNumber | None | object = _SENTINEL
    ) -> None:
        if name is not None:
            self.name = name
        if phone is not PortalUser._SENTINEL:
            self.phone = phone  # type: ignore[assignment]
        self.updated_at = datetime.now(timezone.utc)
