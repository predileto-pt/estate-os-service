import structlog

from properties.container import Container
from properties.domain.exceptions import (
    ExtractionJobNotFoundError,
    InvalidJobTransitionError,
)
from shared.events.types import (
    BATCH_PROPERTY_EXTRACTION_REQUESTED_V1,
    PROPERTY_EXTRACTION_REQUESTED_V1,
)

log = structlog.get_logger()


async def process_event(body: dict, container: Container) -> None:
    event_type = body.get("event_type")

    data = body.get("data", {})
    job_id = data.get("job_id")

    if event_type == PROPERTY_EXTRACTION_REQUESTED_V1:
        if not job_id:
            log.warning("extraction.missing_job_id", body=body)
            return
        try:
            await container.process_property_extraction.execute(job_id=job_id)
        except (InvalidJobTransitionError, ExtractionJobNotFoundError) as exc:
            log.warning("extraction.skip_invalid_state", job_id=job_id, reason=str(exc))
    elif event_type == BATCH_PROPERTY_EXTRACTION_REQUESTED_V1:
        if not job_id:
            log.warning("batch_extraction.missing_job_id", body=body)
            return
        try:
            await container.process_batch_property_extraction.execute(job_id=job_id)
        except (InvalidJobTransitionError, ExtractionJobNotFoundError) as exc:
            log.warning("batch_extraction.skip_invalid_state", job_id=job_id, reason=str(exc))
    else:
        log.warning("extraction.unknown_event_type", event_type=event_type)
