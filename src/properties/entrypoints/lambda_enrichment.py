"""AWS Lambda entrypoint for the property enrichment worker.

Consumes from the `property-enrichment` SQS command queue. One SQS record
per invocation (`batch_size = 1`). Handles `ENRICH_PROPERTY_REQUESTED.v1`
— the Google Places POI fan-out + LLM locality filter pipeline
(ADR-010). Lambda timeout is 15 min (user confirmed real runs stay well
under that); reserved concurrency is capped at 10 to defend Google
Places quota.

Mirrors `_run_enrichment_worker` in `src/properties/entrypoints/worker.py`.
"""

from shared.events.lambda_bootstrap import load_secrets_into_env

load_secrets_into_env()

from properties.adapters.workers.enrichment_processor import (  # noqa: E402
    handle_enrich_property_requested,
)
from properties.container import Container as PropertyContainer  # noqa: E402
from shared.config import Settings, setup_logging  # noqa: E402
from shared.entrypoints import bootstrap as _bootstrap  # noqa: E402
from shared.events.lambda_handler import make_handler  # noqa: E402
from shared.events.router import EventRouter  # noqa: E402
from shared.events.types import ENRICH_PROPERTY_REQUESTED_V1  # noqa: E402


def _build_router() -> EventRouter:
    router = EventRouter()
    router.on(ENRICH_PROPERTY_REQUESTED_V1, handle_enrich_property_requested)
    return router


async def _build_context() -> PropertyContainer:
    """Fresh per-invocation property container. See `lambda_events`."""
    _bootstrap._property_container = None
    _bootstrap._jobs_container = None

    settings = Settings()
    setup_logging(settings.log_level)

    return await _bootstrap.get_property_container()


_router = _build_router()
handler = make_handler(_router, _build_context)
