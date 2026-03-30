from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SlotStatus(StrEnum):
    AVAILABLE = "available"
    BOOKED = "booked"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Slot:
    id: str
    property_id: str
    agent_user_id: str
    organization_id: str
    start_time: datetime
    end_time: datetime
    status: SlotStatus
    created_at: datetime
    updated_at: datetime

    def is_available(self) -> bool:
        return self.status == SlotStatus.AVAILABLE

    def belongs_to_agent(self, user_id: str) -> bool:
        return self.agent_user_id == user_id

    def belongs_to_organization(self, org_id: str) -> bool:
        return self.organization_id == org_id


@dataclass(frozen=True)
class CreateSlotParams:
    property_id: str
    agent_user_id: str
    organization_id: str
    start_time: datetime
    end_time: datetime

    def __post_init__(self) -> None:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
