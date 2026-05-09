from __future__ import annotations

from uuid import UUID

import structlog

from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)
from shared.events.base import DomainEvent
from shared.events.ports import CommandPublisher
from shared.events.types import ENRICH_PROPERTY_REQUESTED_V1
from shared.jobs.application.ports.job_tracker import JobTracker
from shared.jobs.domain.job import JobEntityType, JobKind

log = structlog.get_logger()


class EnqueueEnrichProperty:
    """HTTP-layer use case: validates the property + coordinates, registers
    a unified `Job` row, then publishes ENRICH_PROPERTY_REQUESTED.v1 to the
    property-enrichment-queue with `tracked_job_id` baked in.

    The actual workflow runs in the worker (`EnrichProperty`).
    """

    def __init__(
        self,
        property_repo: PropertyRepository,
        command_publisher: CommandPublisher,
        enrichment_queue_url: str,
        job_tracker: JobTracker | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.command_publisher = command_publisher
        self.enrichment_queue_url = enrichment_queue_url
        self.job_tracker = job_tracker

    async def execute(
        self,
        *,
        property_id: UUID,
        organization_id: UUID,
        force: bool,
        requested_by_user_id: UUID,
    ) -> UUID | None:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None or prop.organization_id != organization_id:
            raise PropertyNotFoundError(str(property_id))

        if prop.latitude is None or prop.longitude is None:
            raise PropertyMissingCoordinatesError(str(property_id))

        tracked_job_id: UUID | None = None
        if self.job_tracker is not None:
            tracked_job_id = await self.job_tracker.start(
                organization_id=organization_id,
                requested_by_user_id=requested_by_user_id,
                kind=JobKind.PROPERTY_ENRICHMENT,
                entity_type=JobEntityType.PROPERTY,
                entity_id=property_id,
                title=f"Descobrir POIs perto de {prop.address}",
            )

        await self.command_publisher.send(
            self.enrichment_queue_url,
            DomainEvent(
                event_type=ENRICH_PROPERTY_REQUESTED_V1,
                data={
                    "property_id": str(property_id),
                    "organization_id": str(organization_id),
                    "force": force,
                    "requested_by_user_id": str(requested_by_user_id),
                    "tracked_job_id": str(tracked_job_id) if tracked_job_id else None,
                },
            ),
        )

        log.info(
            "enrich_property.enqueued",
            property_id=str(property_id),
            organization_id=str(organization_id),
            force=force,
            tracked_job_id=str(tracked_job_id) if tracked_job_id else None,
        )
        return tracked_job_id
