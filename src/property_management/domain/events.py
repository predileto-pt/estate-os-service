from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass(frozen=True)
class DomainEvent:
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Serialize to dict for transport (SQS, etc.)."""
        return {
            "event_type": type(self).__name__,
            "event_id": str(self.event_id),
            "occurred_at": self.occurred_at.isoformat(),
            "data": {
                k: str(v) if isinstance(v, UUID) else v
                for k, v in self.__dict__.items()
                if k not in ("event_id", "occurred_at")
            },
        }


@dataclass(frozen=True)
class PropertyExtractionRequested(DomainEvent):
    job_id: str = ""


@dataclass(frozen=True)
class BatchPropertyExtractionRequested(DomainEvent):
    job_id: str = ""


@dataclass(frozen=True)
class PropertyCreated(DomainEvent):
    property_id: str = ""
