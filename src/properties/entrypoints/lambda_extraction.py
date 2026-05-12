"""AWS Lambda entrypoint for the property extraction worker.

Consumes from the `property-extraction` SQS command queue. One SQS record
per invocation (`batch_size = 1`). Handles both event types the EC2
worker registers — `PROPERTY_EXTRACTION_REQUESTED.v1` and
`BATCH_PROPERTY_EXTRACTION_REQUESTED.v1`. Lambda timeout is 12 min;
reserved concurrency is capped at 10 to defend Reducto + OpenAI rate
limits (see terraform/production/lambda.tf for the cap, ADR-018 for the
rationale).

Mirrors `_run_extraction_worker` in `src/properties/entrypoints/worker.py`.
"""

# Secrets bootstrap before any shared.config import — see
# src/shared/events/lambda_bootstrap.py docstring.
from shared.events.lambda_bootstrap import load_secrets_into_env

load_secrets_into_env()

from properties.adapters.workers.extraction_processor import (  # noqa: E402
    handle_batch_property_extraction_requested,
    handle_property_extraction_requested,
)
from shared.config import Settings, setup_logging  # noqa: E402
from shared.entrypoints import bootstrap as _bootstrap  # noqa: E402
from shared.events.lambda_handler import make_handler  # noqa: E402
from shared.events.router import EventRouter  # noqa: E402
from shared.events.types import (  # noqa: E402
    BATCH_PROPERTY_EXTRACTION_REQUESTED_V1,
    PROPERTY_EXTRACTION_REQUESTED_V1,
)
from properties.container import Container as PropertyContainer  # noqa: E402


def _build_router() -> EventRouter:
    router = EventRouter()
    router.on(PROPERTY_EXTRACTION_REQUESTED_V1, handle_property_extraction_requested)
    router.on(BATCH_PROPERTY_EXTRACTION_REQUESTED_V1, handle_batch_property_extraction_requested)
    return router


async def _build_context() -> PropertyContainer:
    """Fresh per-invocation property container.

    See `lambda_events._build_context` for why the bootstrap globals are
    invalidated before each build.
    """
    _bootstrap._property_container = None
    _bootstrap._jobs_container = None

    settings = Settings()
    setup_logging(settings.log_level)

    return await _bootstrap.get_property_container()


_router = _build_router()
handler = make_handler(_router, _build_context)
