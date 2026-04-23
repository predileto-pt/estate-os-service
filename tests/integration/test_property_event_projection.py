"""Integration test: PublishProperty → PROPERTY_PUBLISHED.v1 → projector.

Wires a real FastAPI app with an in-memory event publisher so that
`POST /publish` actually emits an event. Feeds the emitted event into
`handle_property_event` with a fresh `InMemoryPropertyListingRepository`
and asserts the read-model row lands at `status='active'` with the new
aggregate_version.

Scope notes:

- The public `GET /api/v1/listings/properties` route reads the legacy
  `ReadPropertyModel` (same `properties` table via `extend_existing=True`),
  not `property_listings`. The carried-state spec explicitly leaves the
  swap as a non-goal, so this test does NOT assert through that route —
  the projector write to `property_listings` is the new behavior under
  test. The "publish shows up on the portal" path is covered at the
  properties-admin layer by `TestPublishProperty.test_publish_appears_in_list_active`
  in `tests/integration/test_properties.py`.
- We drive the event through `handle_property_event` directly rather
  than spinning up an SQS worker — the worker's registration of the
  handler for `PROPERTY_PUBLISHED_V1` is a one-line wire in
  `events_worker.py` and reading the code is the practical test for
  that wiring.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)
from listings.adapters.workers.property_event_handler import handle_property_event
from properties.container import Container as PropertyContainer
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_image import PropertyImage
from properties.domain.models.property_owner import PropertyOwner
from properties.domain.models.property_price import PropertyPrice
from shared.events.adapters.inmemory_event_bus import InMemoryEventPublisher
from shared.events.types import (
    PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
    PROPERTY_PUBLISHED_V1,
)
from shared.main import create_app
from tests.conftest import TEST_JWT_SECRET, TEST_ORGANIZATION_ID


@pytest.fixture(autouse=True)
def _auto_seed_member(seed_test_member):
    return seed_test_member


@pytest.fixture
def domain_event_publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


@pytest.fixture
def property_container_with_publisher(
    property_repo,
    document_extractor,
    document_storage,
    extraction_job_repo,
    property_extractor_service,
    command_publisher,
    extraction_queue_url,
    document_classifier,
    document_parser,
    document_content_repo,
    domain_event_publisher,
):
    """Same as the default `property_container` fixture but wires a real
    in-memory event publisher so `PublishProperty` actually emits."""
    return PropertyContainer(
        property_repo=property_repo,
        document_extractor=document_extractor,
        document_storage=document_storage,
        property_extractor=property_extractor_service,
        extraction_job_repo=extraction_job_repo,
        command_publisher=command_publisher,
        extraction_queue_url=extraction_queue_url,
        document_classifier=document_classifier,
        document_parser=document_parser,
        document_content_repo=document_content_repo,
        domain_event_publisher=domain_event_publisher,
    )


@pytest.fixture
def projection_app(
    container,
    identity_container,
    billing_container,
    property_container_with_publisher,
    monkeypatch,
):
    monkeypatch.setattr("shared.config.settings.supabase_jwt_secret", TEST_JWT_SECRET)
    return create_app(
        container=container,
        identity_container=identity_container,
        billing_container=billing_container,
        property_container=property_container_with_publisher,
    )


@pytest.fixture
async def projection_client(projection_app):
    transport = ASGITransport(app=projection_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def property_listing_repo() -> InMemoryPropertyListingRepository:
    return InMemoryPropertyListingRepository()


@pytest.fixture
def projector_context(property_listing_repo):
    """Mirrors the context shape the real listings worker passes
    (`src/listings/entrypoints/events_worker.py:69-72`) — the projector
    pulls repos off `context["listings"]` and publishes enrichment
    events via `context["publisher"]`."""

    class _Listings:
        pass

    listings_ns = _Listings()
    listings_ns.property_listing_repo = property_listing_repo
    # Enrichment publisher: captures fan-out events but does nothing else.
    enrichment_publisher = InMemoryEventPublisher()
    return {
        "listings": listings_ns,
        "publisher": enrichment_publisher,
    }


def _make_publishable(address: str = "Rua Augusta 1, Lisboa") -> Property:
    now = datetime.now(timezone.utc)
    pid = uuid4()
    prop = Property(
        id=pid,
        organization_id=UUID(TEST_ORGANIZATION_ID),
        address=address,
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.DRAFT,
        description=None,
        created_at=now,
        updated_at=now,
    )
    prop.add_owner(
        PropertyOwner(
            id=uuid4(),
            property_id=pid,
            full_name="Maria Silva",
            civil_status=None,
            address=address,
            nif="123456789",
            document_type=None,
            document_id=None,
            issued_by=None,
            issuing_district=None,
            date_of_birth=None,
            created_at=now,
            updated_at=now,
        )
    )
    prop.add_price(
        PropertyPrice(
            id=uuid4(),
            property_id=pid,
            amount=Decimal("350000.00"),
            listing_type=ListingType.SALE,
            created_at=now,
            updated_at=now,
        )
    )
    prop.add_image(
        PropertyImage(
            id=uuid4(),
            property_id=pid,
            s3_key="photos/x.jpg",
            filename="x.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            display_order=0,
            created_at=now,
            updated_at=now,
        )
    )
    prop.bump_version()
    return prop


async def test_publish_route_emits_event_projector_writes_active_row(
    projection_client,
    auth_headers,
    property_repo,
    domain_event_publisher,
    projector_context,
    property_listing_repo,
):
    # Arrange — a draft property saved on the write side.
    prop = _make_publishable()
    version_before = prop.aggregate_version
    await property_repo.save(prop)

    # Act 1 — hit the real HTTP route.
    response = await projection_client.post(
        f"/api/v1/admin/properties/{prop.id}/publish?organization_id={TEST_ORGANIZATION_ID}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"

    # The use case should have emitted exactly one PROPERTY_PUBLISHED.v1
    # through the in-memory publisher wired into the properties container.
    published = [
        e for e in domain_event_publisher.published if e.event_type == PROPERTY_PUBLISHED_V1
    ]
    assert len(published) == 1
    event = published[0]
    assert event.data["id"] == str(prop.id)
    assert event.data["status"] == "active"
    assert event.data["aggregate_version"] == version_before + 1

    # Act 2 — drive the event through the real projector, same as the
    # worker would on receipt.
    await handle_property_event(event, projector_context)

    # Assert — property_listings row exists with status='active' and the
    # source_aggregate_version from the event.
    row = await property_listing_repo.get_by_id(prop.id)
    assert row is not None
    assert row.status.value == "active"
    assert row.source_aggregate_version == version_before + 1
    # The projector also fans out an enrichment event on every applied
    # upsert — same behavior as for CREATED/UPDATED.
    enrichment_events = projector_context["publisher"].published
    assert any(
        e.event_type == PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1 for e in enrichment_events
    )


async def test_projector_drops_older_published_event_on_replay(
    projection_client,
    auth_headers,
    property_repo,
    domain_event_publisher,
    projector_context,
    property_listing_repo,
):
    """Replaying an older PROPERTY_PUBLISHED.v1 (lower aggregate_version)
    must not regress the property_listings row. The existing projector
    idempotency guard covers it; this test locks the behavior in for
    the new event type."""
    prop = _make_publishable()
    # Simulate prior state at v5 by bumping.
    for _ in range(4):
        prop.bump_version()
    await property_repo.save(prop)

    # Publish: event will be at v6.
    response = await projection_client.post(
        f"/api/v1/admin/properties/{prop.id}/publish?organization_id={TEST_ORGANIZATION_ID}",
        headers=auth_headers,
    )
    assert response.status_code == 200

    event = next(
        e for e in domain_event_publisher.published if e.event_type == PROPERTY_PUBLISHED_V1
    )
    # Apply once.
    await handle_property_event(event, projector_context)
    row_after_first = await property_listing_repo.get_by_id(prop.id)
    assert row_after_first.source_aggregate_version == event.data["aggregate_version"]

    # Replay the same event — upsert idempotency-drops (same version).
    projector_context["publisher"].published.clear()
    await handle_property_event(event, projector_context)
    row_after_replay = await property_listing_repo.get_by_id(prop.id)
    assert row_after_replay.source_aggregate_version == row_after_first.source_aggregate_version
    # No enrichment re-fire either — the projector skips it on idempotency drops.
    assert projector_context["publisher"].published == []
