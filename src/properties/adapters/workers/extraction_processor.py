import structlog

from properties.container import Container
from properties.domain.exceptions import (
    ExtractionJobNotFoundError,
    InvalidJobTransitionError,
)
from shared.events.base import DomainEvent

log = structlog.get_logger()


async def handle_property_extraction_requested(event: DomainEvent, container: Container) -> None:
    job_id = event.data.get("job_id")
    if not job_id:
        log.warning("extraction.missing_job_id", event_id=event.event_id)
        return
    try:
        await container.process_property_extraction.execute(job_id=job_id)
    except (InvalidJobTransitionError, ExtractionJobNotFoundError) as exc:
        log.warning("extraction.skip_invalid_state", job_id=job_id, reason=str(exc))


async def handle_batch_property_extraction_requested(
    event: DomainEvent, container: Container
) -> None:
    job_id = event.data.get("job_id")
    if not job_id:
        log.warning("batch_extraction.missing_job_id", event_id=event.event_id)
        return
    try:
        await container.process_batch_property_extraction.execute(job_id=job_id)
    except (InvalidJobTransitionError, ExtractionJobNotFoundError) as exc:
        log.warning("batch_extraction.skip_invalid_state", job_id=job_id, reason=str(exc))
