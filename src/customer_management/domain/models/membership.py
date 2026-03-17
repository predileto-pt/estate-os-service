from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


class MembershipRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


@dataclass
class Membership:
    id: UUID
    user_id: UUID
    organization_id: UUID
    role: MembershipRole
    created_at: datetime
    updated_at: datetime
