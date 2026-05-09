"""Integration tests for the admin org-scoped listings endpoint.

Status-exclusion is intentionally not asserted — see spec §"Status
filtering". The in-memory adapter has no `status` field on
`ListedProperty` to filter on; the SQL `WHERE status = ACTIVE`
predicate is the canonical enforcement and is documented on the
SQLAlchemy adapter method.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from listings.domain.models import ListedProperty, ListingType, Typology
from tests.conftest import TEST_ORGANIZATION_ID

OTHER_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture(autouse=True)
def _auto_seed_member(seed_test_member):
    # Apply to every test in this module so the listings admin route can
    # resolve the JWT's `sub` to a domain User+Membership in
    # TEST_ORGANIZATION_ID via require_org_member.
    return seed_test_member


def _make_listed(
    *,
    organization_id: str = TEST_ORGANIZATION_ID,
    address: str = "Rua A",
    description: str | None = None,
) -> ListedProperty:
    """Build a `ListedProperty` for in-memory seeding.

    `ListedProperty` carries no `status` field — the in-memory adapter
    treats every seeded row as visible. See the spec §"Status filtering"
    for why that's intentional.
    """
    now = datetime.now(timezone.utc)
    return ListedProperty(
        id=uuid4(),
        organization_id=UUID(organization_id),
        address=address,
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        description=description,
        characteristics=None,
        latitude=None,
        longitude=None,
        created_at=now,
        updated_at=now,
    )


class TestAdminOrgActiveListings:
    async def test_happy_path_returns_only_calling_org_rows(
        self, client, auth_headers, listing_repo
    ):
        # Description is used as the per-row tag now that `address` is
        # no longer in the public response (privacy fix, spec
        # 2026-05-property-address-enrichment-fix).
        listing_repo.add(_make_listed(address="Mine — 1", description="Mine — 1"))
        listing_repo.add(_make_listed(address="Mine — 2", description="Mine — 2"))

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # No `address` exposed. Use description as a stable per-row marker.
        descs = {item["description"] for item in data["items"]}
        assert descs == {"Mine — 1", "Mine — 2"}
        assert all("address" not in item for item in data["items"])
        assert data["total"] == 2
        assert data["limit"] == 20
        assert data["offset"] == 0

    async def test_other_orgs_rows_are_not_included(self, client, auth_headers, listing_repo):
        listing_repo.add(_make_listed(address="Mine", description="Mine"))
        listing_repo.add(
            _make_listed(
                organization_id=OTHER_ORGANIZATION_ID, address="Theirs", description="Theirs"
            )
        )

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        descs = {item["description"] for item in response.json()["items"]}
        assert descs == {"Mine"}

    async def test_empty_org_returns_200_with_empty_items(self, client, auth_headers, listing_repo):
        # Other orgs have rows; calling org has none.
        listing_repo.add(_make_listed(organization_id=OTHER_ORGANIZATION_ID, address="Theirs"))

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_cross_org_call_returns_403(self, client, auth_headers, listing_repo):
        """Caller is a member of TEST_ORGANIZATION_ID only — querying
        OTHER_ORGANIZATION_ID must be blocked by require_org_member."""
        listing_repo.add(_make_listed(organization_id=OTHER_ORGANIZATION_ID, address="Theirs"))

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403

    async def test_unauthenticated_returns_401(self, client, listing_repo):
        listing_repo.add(_make_listed(address="Mine"))

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}",
        )
        assert response.status_code == 401

    async def test_pagination_limit_and_offset(self, client, auth_headers, listing_repo):
        for i in range(5):
            listing_repo.add(_make_listed(address=f"Row {i}"))

        # First page: limit=2, offset=0 — expect 2 items, total=5.
        page_one = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}"
            f"&limit=2&offset=0",
            headers=auth_headers,
        )
        assert page_one.status_code == 200
        page_one_data = page_one.json()
        assert len(page_one_data["items"]) == 2
        assert page_one_data["total"] == 5
        assert page_one_data["limit"] == 2
        assert page_one_data["offset"] == 0

        # Second page: limit=2, offset=2 — expect 2 items, total still 5.
        page_two = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}"
            f"&limit=2&offset=2",
            headers=auth_headers,
        )
        assert page_two.status_code == 200
        page_two_data = page_two.json()
        assert len(page_two_data["items"]) == 2
        assert page_two_data["total"] == 5

    async def test_limit_above_max_returns_422(self, client, auth_headers):
        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}&limit=200",
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_response_shape_matches_listed_property_response(
        self, client, auth_headers, listing_repo
    ):
        listing_repo.add(_make_listed(address="Shape check"))

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        item = response.json()["items"][0]
        # Same field set as the public endpoint's response.
        # `address` removed (privacy fix, spec
        # 2026-05-property-address-enrichment-fix).
        for key in (
            "id",
            "listing_type",
            "typology",
            "description",
            "characteristics",
            "latitude",
            "longitude",
            "created_at",
            "updated_at",
            "prices",
            "images",
        ):
            assert key in item
        assert "address" not in item
