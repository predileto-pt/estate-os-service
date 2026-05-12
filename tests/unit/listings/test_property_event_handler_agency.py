"""Projector test: agency contact is resolved + written on each PROPERTY_* event.

Spec: 2026-05-listings-agency-contact.
"""

from uuid import UUID, uuid4

import pytest

from listings.adapters.inmemory.inmemory_property_listing_repo import (
    InMemoryPropertyListingRepository,
)
from listings.adapters.workers.property_event_handler import handle_property_event
from listings.application.ports.get_agency_contact import AgencyContact
from shared.events.base import DomainEvent
from shared.events.types import PROPERTY_CREATED_V1, PROPERTY_UPDATED_V1


class _StubAgencyContactResolver:
    """Returns a fixed contact for any org_id; records every call."""

    def __init__(self, contact: AgencyContact) -> None:
        self._contact = contact
        self.calls: list[UUID] = []

    async def execute(self, organization_id: UUID) -> AgencyContact:
        self.calls.append(organization_id)
        return self._contact


@pytest.fixture
def repo():
    return InMemoryPropertyListingRepository()


@pytest.fixture
def agency_contact():
    return AgencyContact(
        name="Predileto Imobiliária",
        email="agent@predileto.pt",
        phone="+351 912345678",
    )


@pytest.fixture
def resolver(agency_contact):
    return _StubAgencyContactResolver(agency_contact)


@pytest.fixture
def context(repo, resolver):
    class _Listings:
        pass

    listings = _Listings()
    listings.property_listing_repo = repo
    listings.get_agency_contact = resolver
    return {"listings": listings, "publisher": None}


def _snapshot(*, id_: str | None = None, org_id: str | None = None, version: int = 1) -> dict:
    return {
        "id": id_ or str(uuid4()),
        "organization_id": org_id or str(uuid4()),
        "aggregate_version": version,
        "address": "Arca, Ponte de Lima, Viana",
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


async def test_created_event_writes_agency_columns(context, repo, resolver, agency_contact):
    data = _snapshot()
    await handle_property_event(DomainEvent(event_type=PROPERTY_CREATED_V1, data=data), context)

    row = await repo.get_by_id(UUID(data["id"]))
    assert row is not None
    assert row.agency_name == agency_contact.name
    assert row.agency_email == agency_contact.email
    assert row.agency_phone == agency_contact.phone
    assert resolver.calls == [UUID(data["organization_id"])]


async def test_updated_event_refreshes_agency_columns(context, repo, resolver):
    # Initial CREATED with one agency contact.
    data = _snapshot(version=1)
    await handle_property_event(DomainEvent(event_type=PROPERTY_CREATED_V1, data=data), context)

    # Resolver now returns a different agency name (simulates org rename
    # since the last property event).
    resolver._contact = AgencyContact(name="Renamed Agency", email="agent@predileto.pt", phone=None)

    await handle_property_event(
        DomainEvent(
            event_type=PROPERTY_UPDATED_V1,
            data=_snapshot(id_=data["id"], org_id=data["organization_id"], version=2),
        ),
        context,
    )

    row = await repo.get_by_id(UUID(data["id"]))
    assert row is not None
    assert row.agency_name == "Renamed Agency"
    assert row.agency_phone is None


async def test_resolver_missing_from_context_keeps_columns_null(repo):
    """Legacy paths that don't wire the port — agency stays NULL, no crash."""

    class _Listings:
        pass

    listings = _Listings()
    listings.property_listing_repo = repo
    # Intentionally NOT setting `get_agency_contact`.

    data = _snapshot()
    await handle_property_event(
        DomainEvent(event_type=PROPERTY_CREATED_V1, data=data),
        {"listings": listings, "publisher": None},
    )

    row = await repo.get_by_id(UUID(data["id"]))
    assert row is not None
    assert row.agency_name is None
    assert row.agency_email is None
    assert row.agency_phone is None
