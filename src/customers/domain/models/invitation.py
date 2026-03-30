from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from customers.domain.models.membership import MembershipRole


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class Invitation:
    id: UUID
    organization_id: UUID
    email: str
    role: MembershipRole
    invited_by: UUID
    token: str
    status: InvitationStatus
    expires_at: datetime
    created_at: datetime
