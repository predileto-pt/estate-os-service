from __future__ import annotations

from uuid import UUID

import structlog

from properties.application.events.property_event import emit_property_deleted
from properties.application.ports.document_storage import DocumentStorage
from properties.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import PropertyNotFoundError
from shared.events.ports import EventPublisher

log = structlog.get_logger()


class DeleteProperty:
    """Hard-delete a property and everything that belongs to it.

    Order of operations:
        1. Delete the S3 image objects (best-effort — missing keys are ignored).
        2. Delete extraction jobs linked to the property (cascades document_contents).
        3. Delete the property and its child rows (owners, prices, images, amenities).

    S3 deletes happen first so that if the database transaction later fails the
    user can simply retry. Database deletes happen in a single repository call
    so they are atomic with respect to each other.
    """

    def __init__(
        self,
        property_repo: PropertyRepository,
        extraction_job_repo: ExtractionJobRepository,
        image_storage: DocumentStorage,
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.extraction_job_repo = extraction_job_repo
        self.image_storage = image_storage
        self.domain_event_publisher = domain_event_publisher

    async def execute(self, *, property_id: UUID, organization_id: UUID) -> None:
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None:
            raise PropertyNotFoundError(str(property_id))

        if prop.organization_id != organization_id:
            # Caller passed an org that does not own this property — same as not found
            raise PropertyNotFoundError(str(property_id))

        # 1. Delete S3 image objects
        for image in prop.images:
            try:
                await self.image_storage.delete(image.s3_key)
            except Exception as exc:
                log.warning(
                    "delete_property.s3_delete_failed",
                    property_id=str(property_id),
                    s3_key=image.s3_key,
                    error=str(exc),
                )

        # 2. Delete extraction jobs (and their document_contents)
        await self.extraction_job_repo.delete_by_property_id(property_id)

        # 3. Bump the aggregate version one last time on the snapshot we
        # already loaded — the projector uses this as the idempotency
        # guard for the deletion event. We don't persist it because the
        # row is about to be deleted anyway.
        prop.aggregate_version += 1

        # 4. Delete property + child rows
        await self.property_repo.delete(property_id)

        # 5. Emit PROPERTY_DELETED.v1 after the delete commits, using the
        # minimal {id, organization_id, aggregate_version} payload.
        await emit_property_deleted(self.domain_event_publisher, prop)

        log.info(
            "property_deleted",
            property_id=str(property_id),
            organization_id=str(organization_id),
            num_images_deleted=len(prop.images),
        )
