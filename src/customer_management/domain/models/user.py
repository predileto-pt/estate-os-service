from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from customer_management.domain.models.value_objects import PhoneNumber


@dataclass
class User:
    id: UUID
    supabase_user_id: str  # maps to auth.users.id
    email: str
    name: str
    phone: PhoneNumber | None
    company_id: UUID  # FK → Company
    google_metadata: dict | None
    created_at: datetime
    updated_at: datetime
