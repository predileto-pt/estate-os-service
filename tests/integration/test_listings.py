"""Integration tests for the admin org-scoped listings endpoint.

Migrated from the legacy `ListingRepository` (read mapping over the
live `properties` table) to `PropertyListingRepository` (carried-state
projection). The route now reads from the projection — status filtering
is real (`property_listings.status='active'`), and the response shape
is the lean projection shape (no `filename`/`content_type`/`size_bytes`
on images, no `id` on prices).
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from tests.conftest import TEST_ORGANIZATION_ID

OTHER_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture(autouse=True)
def _auto_seed_member(seed_test_member):
    # Apply to every test in this module so the listings admin route can
    # resolve the JWT's `sub` to a domain User+Membership in
    # TEST_ORGANIZATION_ID via require_org_member.
    return seed_test_member


async def _seed_listing(
    property_listing_repo,
    *,
    organization_id: str = TEST_ORGANIZATION_ID,
    description: str | None = None,
    status: str = "active",
    listing_type: str = "sale",
    typology: str = "apartment",
    address: str = "Rua A, Lisboa",
):
    """Drop a row directly via the projection upsert. Mirrors the
    snapshot shape `build_property_snapshot()` produces."""
    snapshot = {
        "id": str(uuid4()),
        "organization_id": organization_id,
        "aggregate_version": 1,
        "address": address,
        "listing_type": listing_type,
        "typology": typology,
        "status": status,
        "description": description,
        "latitude": None,
        "longitude": None,
        "characteristics": None,
        "prices": [],
        "images": [],
    }
    await property_listing_repo.upsert_from_event(
        event_data=snapshot,
        source_occurred_at=datetime.now(timezone.utc),
    )
    return snapshot


class TestAdminOrgActiveListings:
    async def test_happy_path_returns_only_calling_org_rows(
        self, client, auth_headers, property_listing_repo
    ):
        await _seed_listing(property_listing_repo, description="Mine — 1")
        await _seed_listing(property_listing_repo, description="Mine — 2")

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        descs = {item["description"] for item in data["items"]}
        assert descs == {"Mine — 1", "Mine — 2"}
        assert all("address" not in item for item in data["items"])
        assert data["total"] == 2
        assert data["limit"] == 20
        assert data["offset"] == 0

    async def test_other_orgs_rows_are_not_included(
        self, client, auth_headers, property_listing_repo
    ):
        await _seed_listing(property_listing_repo, description="Mine")
        await _seed_listing(
            property_listing_repo,
            organization_id=OTHER_ORGANIZATION_ID,
            description="Theirs",
        )

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        descs = {item["description"] for item in response.json()["items"]}
        assert descs == {"Mine"}

    async def test_empty_org_returns_200_with_empty_items(
        self, client, auth_headers, property_listing_repo
    ):
        await _seed_listing(
            property_listing_repo,
            organization_id=OTHER_ORGANIZATION_ID,
            description="Theirs",
        )

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_non_active_rows_excluded(self, client, auth_headers, property_listing_repo):
        """The projection has `status` as a real column. Non-ACTIVE
        rows are filtered out at the repo level."""
        await _seed_listing(property_listing_repo, description="Active", status="active")
        await _seed_listing(property_listing_repo, description="Draft", status="draft")
        await _seed_listing(property_listing_repo, description="Sold", status="sold")

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        descs = {item["description"] for item in response.json()["items"]}
        assert descs == {"Active"}

    async def test_cross_org_call_returns_403(self, client, auth_headers, property_listing_repo):
        """Caller is a member of TEST_ORGANIZATION_ID only — querying
        OTHER_ORGANIZATION_ID must be blocked by require_org_member."""
        await _seed_listing(
            property_listing_repo,
            organization_id=OTHER_ORGANIZATION_ID,
            description="Theirs",
        )

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403

    async def test_unauthenticated_returns_401(self, client, property_listing_repo):
        await _seed_listing(property_listing_repo, description="Mine")

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}",
        )
        assert response.status_code == 401

    async def test_pagination_limit_and_offset(self, client, auth_headers, property_listing_repo):
        for i in range(5):
            await _seed_listing(property_listing_repo, description=f"Row {i}")

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
        self, client, auth_headers, property_listing_repo
    ):
        await _seed_listing(property_listing_repo, description="Shape check")

        response = await client.get(
            f"/api/v1/admin/listings/properties?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        item = response.json()["items"][0]
        # Same field set as the public endpoint's response.
        # `address` removed (privacy fix). Structured location now exposed.
        for key in (
            "id",
            "listing_type",
            "typology",
            "description",
            "characteristics",
            "parish",
            "municipality",
            "district",
            "country",
            "latitude",
            "longitude",
            "created_at",
            "updated_at",
            "prices",
            "images",
        ):
            assert key in item
        assert "address" not in item
