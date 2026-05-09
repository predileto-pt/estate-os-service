"""Unit tests for `handle_address_enrichment`.

Three cases:
- Searcher succeeds → row's parish/municipality/district patched (PT
  shape), `location_enrichment_attempts` bumped.
- Searcher raises → handler increments attempts AND re-raises
  `AddressParseError` so the shared SQSWorker nacks and SQS redelivers.
- Row already deleted (enrichment message lagged behind a DELETED event)
  → handler logs and returns without raising.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from listings.adapters.inmemory.inmemory_address_searcher import InMemoryAddressSearcher
from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)
from listings.adapters.workers.address_enrichment_handler import handle_address_enrichment
from listings.domain.exceptions import AddressParseError
from shared.events.base import DomainEvent
from shared.events.types import PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1


class _FailingSearcher:
    def __init__(self):
        self.calls = 0

    async def search(self, *, address: str, postal_code, country):
        self.calls += 1
        raise RuntimeError("LLM boom")


@pytest.fixture
def repo():
    return InMemoryPropertyListingRepository()


async def _seed_listing_async(
    repo, pid: str, address: str = "Arca, Ponte de Lima, Viana do Castelo"
):
    event_data = {
        "id": pid,
        "organization_id": str(uuid4()),
        "aggregate_version": 1,
        "address": address,
        "listing_type": "sale",
        "typology": "apartment",
        "status": "active",
        "description": None,
        "latitude": None,
        "longitude": None,
        "characteristics": None,
        "prices": [],
        "images": [],
    }
    await repo.upsert_from_event(
        event_data=event_data,
        source_occurred_at=datetime.now(timezone.utc),
    )


async def test_searcher_success_patches_location(repo):
    pid = str(uuid4())
    await _seed_listing_async(repo, pid)

    class _Listings:
        pass

    listings = _Listings()
    listings.property_listing_repo = repo
    listings.portugal_address_searcher = InMemoryAddressSearcher()
    context = {"listings": listings}

    event = DomainEvent(
        event_type=PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
        data={
            "property_id": pid,
            "address": "Arca, Ponte de Lima, Viana do Castelo",
            "postal_code": None,
            "country": "Portugal",
        },
    )
    await handle_address_enrichment(event, context)

    row = await repo.get_by_id(UUID(pid))
    assert row.parish == "Arca"
    assert row.municipality == "Ponte de Lima"
    assert row.district == "Viana do Castelo"
    assert row.country == "Portugal"
    assert row.location_enrichment_attempts == 1
    assert row.location_enriched_at is not None


async def test_country_defaults_to_portugal_when_event_missing_field(repo):
    """Backward-compat: legacy events without `country` still process."""
    pid = str(uuid4())
    await _seed_listing_async(repo, pid)

    class _Listings:
        pass

    listings = _Listings()
    listings.property_listing_repo = repo
    listings.portugal_address_searcher = InMemoryAddressSearcher()
    context = {"listings": listings}

    event = DomainEvent(
        event_type=PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
        data={
            "property_id": pid,
            "address": "Arca, Ponte de Lima, Viana do Castelo",
            # No country, no postal_code — pre-spec event shape.
        },
    )
    await handle_address_enrichment(event, context)

    row = await repo.get_by_id(UUID(pid))
    assert row.district == "Viana do Castelo"


async def test_searcher_failure_bumps_attempts_and_reraises(repo):
    pid = str(uuid4())
    await _seed_listing_async(repo, pid)

    class _Listings:
        pass

    listings = _Listings()
    listings.property_listing_repo = repo
    listings.portugal_address_searcher = _FailingSearcher()
    context = {"listings": listings}

    event = DomainEvent(
        event_type=PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
        data={
            "property_id": pid,
            "address": "whatever",
            "postal_code": "1000-001",
            "country": "Portugal",
        },
    )
    with pytest.raises(AddressParseError):
        await handle_address_enrichment(event, context)

    row = await repo.get_by_id(UUID(pid))
    # Attempts bumped, location still NULL.
    assert row.location_enrichment_attempts == 1
    assert row.parish is None
    assert row.municipality is None
    assert row.district is None
    assert row.location_enriched_at is None


async def test_enrichment_for_deleted_row_returns_without_raising(repo):
    class _Listings:
        pass

    listings = _Listings()
    listings.property_listing_repo = repo  # repo is empty
    listings.portugal_address_searcher = InMemoryAddressSearcher()
    context = {"listings": listings}

    event = DomainEvent(
        event_type=PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT_V1,
        data={
            "property_id": str(uuid4()),
            "address": "Some, Where, Here",
            "postal_code": None,
            "country": "Portugal",
        },
    )
    # Should not raise — the listing was deleted between the PROPERTY_*
    # event and this enrichment message. Handler silently drops.
    await handle_address_enrichment(event, context)
