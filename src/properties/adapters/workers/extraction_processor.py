import structlog

from properties.container import Container

log = structlog.get_logger()


async def process_event(body: dict, container: Container) -> None:
    event_type = body.get("event_type")

    data = body.get("data", {})
    job_id = data.get("job_id")

    if event_type == "PROPERTY_EXTRACTION_REQUESTED":
        if not job_id:
            log.warning("extraction.missing_job_id", body=body)
            return
        await container.process_property_extraction.execute(job_id=job_id)
    elif event_type == "BATCH_PROPERTY_EXTRACTION_REQUESTED":
        if not job_id:
            log.warning("batch_extraction.missing_job_id", body=body)
            return
        await container.process_batch_property_extraction.execute(job_id=job_id)
    else:
        log.warning("extraction.unknown_event_type", event_type=event_type)
