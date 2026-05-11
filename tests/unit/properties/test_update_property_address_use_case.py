"""Unit tests for `UpdatePropertyAddress` — orchestration around
`Property.update_address()`.

Covers:
- Happy path: persists, bumps version, emits PROPERTY_UPDATED.v1 with the
  build_property_snapshot payload, returns the refreshed aggregate.
- No-op short-circuit: unchanged value (or whitespace variant of it) skips
  the write, version bump, and event emission.
- Org-scope check: cross-org / unknown id collapses to PropertyNotFoundError
  before any write.
- Domain validation bubbles through: empty address raises and never writes.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.events.property_event import build_property_snapshot
from properties.application.use_cases.update_property_address import UpdatePropertyAddress
from properties.domain.exceptions import (
    PropertyAddressInvalidError,
    PropertyNotFoundError,
)
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from shared.events.adapters.inmemory_event_bus import InMemoryEventPublisher
from shared.events.types import PROPERTY_UPDATED_V1

ORG_ID = UUID("00000000-0000-0000-0000-000000000010")
OTHER_ORG_ID = UUID("00000000-0000-0000-0000-000000000099")


def _property(
    *,
    address: str = "Rua Original 1",
    organization_id: UUID = ORG_ID,
    status: PropertyStatus = PropertyStatus.DRAFT,
) -> Property:
    now = datetime.now(timezone.utc)
    prop = Property(
        id=uuid4(),
        organization_id=organization_id,
        title="Test property",
        address=address,
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=status,
        description=None,
        created_at=now,
        updated_at=now,
    )
    prop.bump_version()
    return prop


@pytest.fixture
def repo() -> InMemoryPropertyRepository:
    return InMemoryPropertyRepository()


@pytest.fixture
def publisher() -> InMemoryEventPublisher:
    return InMemoryEventPublisher()


async def test_happy_path_persists_bumps_emits(repo, publisher):
    prop = _property(address="Old Addr")
    await repo.save(prop)
    version_before = prop.aggregate_version

    use_case = UpdatePropertyAddress(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, address="Rua Nova 5, Porto"
    )

    assert refreshed.address == "Rua Nova 5, Porto"
    assert refreshed.aggregate_version == version_before + 1

    stored = await repo.get_by_id(prop.id)
    assert stored.address == "Rua Nova 5, Porto"
    assert stored.aggregate_version == version_before + 1

    assert len(publisher.published) == 1
    event = publisher.published[0]
    assert event.event_type == PROPERTY_UPDATED_V1
    assert event.data == build_property_snapshot(refreshed)
    assert event.data["address"] == "Rua Nova 5, Porto"
    assert event.data["aggregate_version"] == version_before + 1


async def test_strips_surrounding_whitespace_in_response(repo, publisher):
    prop = _property(address="Old")
    await repo.save(prop)

    use_case = UpdatePropertyAddress(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, address="  Rua Nova  "
    )

    assert refreshed.address == "Rua Nova"
    stored = await repo.get_by_id(prop.id)
    assert stored.address == "Rua Nova"


async def test_no_op_when_value_unchanged(repo, publisher):
    """Same address, after normalization → no write, no bump, no event."""
    prop = _property(address="Rua Igual")
    await repo.save(prop)
    version_before = prop.aggregate_version

    use_case = UpdatePropertyAddress(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, address="Rua Igual"
    )

    assert refreshed.address == "Rua Igual"
    assert refreshed.aggregate_version == version_before
    assert publisher.published == []


async def test_no_op_when_only_whitespace_differs(repo, publisher):
    """Stripping makes the value identical → still a no-op."""
    prop = _property(address="Rua Igual")
    await repo.save(prop)
    version_before = prop.aggregate_version

    use_case = UpdatePropertyAddress(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, address="  Rua Igual  "
    )

    assert refreshed.aggregate_version == version_before
    assert publisher.published == []


async def test_unknown_id_raises_not_found(repo, publisher):
    use_case = UpdatePropertyAddress(property_repo=repo, domain_event_publisher=publisher)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=uuid4(), organization_id=ORG_ID, address="Rua X")
    assert publisher.published == []


async def test_wrong_org_collapses_to_not_found(publisher):
    """Cross-org load: the use case raises before any write."""

    class TrackingRepo(InMemoryPropertyRepository):
        def __init__(self) -> None:
            super().__init__()
            self.update_address_calls = 0
            self.bump_calls = 0

        async def update_address(self, property_id, address):
            self.update_address_calls += 1
            await super().update_address(property_id, address)

        async def bump_aggregate_version(self, property_id):
            self.bump_calls += 1
            return await super().bump_aggregate_version(property_id)

    tracking_repo = TrackingRepo()
    prop = _property(organization_id=ORG_ID, address="Original")
    await tracking_repo.save(prop)

    use_case = UpdatePropertyAddress(property_repo=tracking_repo, domain_event_publisher=publisher)
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=prop.id, organization_id=OTHER_ORG_ID, address="Rua X")

    assert tracking_repo.update_address_calls == 0
    assert tracking_repo.bump_calls == 0
    assert publisher.published == []
    stored = await tracking_repo.get_by_id(prop.id)
    assert stored.address == "Original"


async def test_empty_address_raises_invalid(repo, publisher):
    """Defense-in-depth: domain-level invariant fires for non-HTTP callers."""
    prop = _property(address="Original")
    await repo.save(prop)

    use_case = UpdatePropertyAddress(property_repo=repo, domain_event_publisher=publisher)
    with pytest.raises(PropertyAddressInvalidError):
        await use_case.execute(property_id=prop.id, organization_id=ORG_ID, address="   ")

    stored = await repo.get_by_id(prop.id)
    assert stored.address == "Original"
    assert publisher.published == []


async def test_works_for_active_property(repo, publisher):
    """Editing an ACTIVE property's address is allowed and emits UPDATED."""
    prop = _property(address="Old", status=PropertyStatus.ACTIVE)
    await repo.save(prop)

    use_case = UpdatePropertyAddress(property_repo=repo, domain_event_publisher=publisher)
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, address="Rua Nova"
    )

    assert refreshed.status == PropertyStatus.ACTIVE
    assert refreshed.address == "Rua Nova"
    assert publisher.published[0].event_type == PROPERTY_UPDATED_V1


async def test_publish_failure_is_swallowed(repo):
    """Same as CreateProperty / UpdatePropertyOwnerContact: persistence has
    already committed by the time we publish, so a broken publisher must
    not fail the whole use case."""
    prop = _property(address="Old")
    await repo.save(prop)

    class BrokenPublisher:
        async def publish(self, _event):
            raise RuntimeError("SNS is down")

    use_case = UpdatePropertyAddress(property_repo=repo, domain_event_publisher=BrokenPublisher())
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, address="Rua Nova"
    )

    assert refreshed.address == "Rua Nova"
    stored = await repo.get_by_id(prop.id)
    assert stored.address == "Rua Nova"


async def test_no_publisher_wired_is_fine(repo):
    """Bootstrap may construct UpdatePropertyAddress without a publisher."""
    prop = _property(address="Old")
    await repo.save(prop)

    use_case = UpdatePropertyAddress(property_repo=repo, domain_event_publisher=None)
    refreshed = await use_case.execute(
        property_id=prop.id, organization_id=ORG_ID, address="Rua Nova"
    )

    assert refreshed.address == "Rua Nova"
