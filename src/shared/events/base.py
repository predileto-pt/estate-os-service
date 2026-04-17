import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class DomainEvent:
    event_type: str
    data: dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "data": self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DomainEvent":
        return cls(
            event_type=d["event_type"],
            data=d.get("data", {}),
            event_id=d.get("event_id", str(uuid4())),
            occurred_at=d.get("occurred_at", datetime.now(timezone.utc).isoformat()),
        )
