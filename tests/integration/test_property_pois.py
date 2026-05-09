"""Integration tests for the property POI endpoints.

POST/GET/PATCH/DELETE on /api/v1/admin/properties/{id}/pois — manual entry.
POST /api/v1/admin/properties/{id}/enrich — auto-discovery workflow trigger.
"""

from uuid import UUID

import pytest

from shared.events.types import ENRICH_PROPERTY_REQUESTED_V1
from tests.conftest import TEST_ORGANIZATION_ID

OTHER_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture(autouse=True)
def _auto_seed_member(seed_test_member):
    return seed_test_member


async def _create_property(client, auth_headers) -> str:
    resp = await client.post(
        "/api/v1/admin/properties/",
        json={
            "organization_id": TEST_ORGANIZATION_ID,
            "address": "Rua das Flores 123",
            "listing_type": "sale",
            "typology": "apartment",
        },
        headers=auth_headers,
    )
    return resp.json()["id"]


def _poi_payload(category: str = "grocery", name: str = "Pingo Doce", **overrides) -> dict:
    base = {
        "category": category,
        "name": name,
        "distance_meters": 200.0,
        "latitude": 38.768,
        "longitude": -9.108,
    }
    base.update(overrides)
    return base


class TestPropertyPois:
    async def test_replace_happy_path(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)

        response = await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload(name="Pingo Doce"), _poi_payload(name="Lidl")]},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert all(p["manually_edited"] is True for p in data)
        assert all("id" in p for p in data)
        assert all(p["created_at"] for p in data)
        assert all(p["updated_at"] for p in data)

    async def test_replace_replaces(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)

        # First call.
        first = await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload(name="First")]},
            headers=auth_headers,
        )
        first_id = first.json()[0]["id"]

        # Second call.
        second = await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload(name="Second")]},
            headers=auth_headers,
        )
        assert second.status_code == 200

        # GET — only Second remains.
        listing = await client.get(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        names = {p["name"] for p in listing.json()}
        ids = {p["id"] for p in listing.json()}
        assert names == {"Second"}
        assert first_id not in ids

    async def test_replace_with_metadata_round_trips(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)

        await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={
                "pois": [
                    _poi_payload(
                        category="school",
                        name="Escola Básica",
                        metadata={"school_type": "public", "rating": 4.2},
                    )
                ]
            },
            headers=auth_headers,
        )
        listing = await client.get(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert listing.json()[0]["metadata"] == {"school_type": "public", "rating": 4.2}

    async def test_replace_empty_clears_catalog(self, client, auth_headers, property_repo):
        from uuid import UUID

        property_id = await _create_property(client, auth_headers)

        # Seed.
        await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload(name="Will be cleared")]},
            headers=auth_headers,
        )
        version_after_seed = (await property_repo.get_by_id(UUID(property_id))).aggregate_version

        # Clear.
        response = await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": []},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json() == []

        listing = await client.get(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert listing.json() == []

        version_after_clear = (await property_repo.get_by_id(UUID(property_id))).aggregate_version
        assert version_after_clear == version_after_seed + 1

    async def test_patch_partial_update(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        seed = await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload(name="Original")]},
            headers=auth_headers,
        )
        poi_id = seed.json()[0]["id"]

        response = await client.patch(
            f"/api/v1/admin/properties/{property_id}/pois/{poi_id}?organization_id={TEST_ORGANIZATION_ID}",
            json={"distance_meters": 320.0},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["distance_meters"] == 320.0
        assert data["name"] == "Original"  # unchanged
        assert data["category"] == "grocery"  # unchanged
        assert data["manually_edited"] is True

    async def test_patch_metadata_round_trips(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        seed = await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload()]},
            headers=auth_headers,
        )
        poi_id = seed.json()[0]["id"]

        response = await client.patch(
            f"/api/v1/admin/properties/{property_id}/pois/{poi_id}?organization_id={TEST_ORGANIZATION_ID}",
            json={"metadata": {"new_key": "value", "rating": 5}},
            headers=auth_headers,
        )
        assert response.status_code == 200
        listing = await client.get(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert listing.json()[0]["metadata"] == {"new_key": "value", "rating": 5}

    async def test_delete_removes_poi(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        seed = await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload()]},
            headers=auth_headers,
        )
        poi_id = seed.json()[0]["id"]

        response = await client.delete(
            f"/api/v1/admin/properties/{property_id}/pois/{poi_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 204

        listing = await client.get(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert listing.json() == []

    async def test_delete_missing_returns_404(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        bogus_poi_id = "00000000-0000-0000-0000-0000000000ff"

        response = await client.delete(
            f"/api/v1/admin/properties/{property_id}/pois/{bogus_poi_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_patch_cross_property_returns_404(self, client, auth_headers):
        prop_a = await _create_property(client, auth_headers)
        prop_b = await _create_property(client, auth_headers)

        seed_b = await client.post(
            f"/api/v1/admin/properties/{prop_b}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload(name="Belongs to B")]},
            headers=auth_headers,
        )
        poi_b_id = seed_b.json()[0]["id"]

        # Try to PATCH POI under prop_a's URL.
        response = await client.patch(
            f"/api/v1/admin/properties/{prop_a}/pois/{poi_b_id}?organization_id={TEST_ORGANIZATION_ID}",
            json={"name": "Hijack"},
            headers=auth_headers,
        )
        assert response.status_code == 404

        # POI under B is unchanged.
        listing_b = await client.get(
            f"/api/v1/admin/properties/{prop_b}/pois?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert listing_b.json()[0]["name"] == "Belongs to B"

    async def test_unknown_property_returns_404(self, client, auth_headers):
        bogus = "00000000-0000-0000-0000-0000000000ff"
        response = await client.get(
            f"/api/v1/admin/properties/{bogus}/pois?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_cross_org_returns_403(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        response = await client.get(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403

    async def test_unauthenticated_returns_401(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        response = await client.get(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
        )
        assert response.status_code == 401

    async def test_invalid_body_returns_422(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)

        # Negative distance_meters.
        bad_distance = await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload(distance_meters=-1.0)]},
            headers=auth_headers,
        )
        assert bad_distance.status_code == 422

        # Latitude out of range.
        bad_lat = await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload(latitude=95.0)]},
            headers=auth_headers,
        )
        assert bad_lat.status_code == 422

        # Empty name.
        empty_name = await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload(name="")]},
            headers=auth_headers,
        )
        assert empty_name.status_code == 422

    async def test_pois_list_max_length_returns_422(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        too_many = [_poi_payload(name=f"P{i}") for i in range(201)]

        response = await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": too_many},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_aggregate_version_bumped_on_post(self, client, auth_headers, property_repo):
        from uuid import UUID

        property_id = await _create_property(client, auth_headers)
        before = (await property_repo.get_by_id(UUID(property_id))).aggregate_version

        await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload()]},
            headers=auth_headers,
        )

        after = (await property_repo.get_by_id(UUID(property_id))).aggregate_version
        assert after == before + 1

    async def test_aggregate_version_bumped_on_patch_and_delete(
        self, client, auth_headers, property_repo
    ):
        from uuid import UUID

        property_id = await _create_property(client, auth_headers)
        seed = await client.post(
            f"/api/v1/admin/properties/{property_id}/pois?organization_id={TEST_ORGANIZATION_ID}",
            json={"pois": [_poi_payload()]},
            headers=auth_headers,
        )
        poi_id = seed.json()[0]["id"]
        version_after_post = (await property_repo.get_by_id(UUID(property_id))).aggregate_version

        # PATCH bumps.
        await client.patch(
            f"/api/v1/admin/properties/{property_id}/pois/{poi_id}?organization_id={TEST_ORGANIZATION_ID}",
            json={"distance_meters": 100.0},
            headers=auth_headers,
        )
        version_after_patch = (await property_repo.get_by_id(UUID(property_id))).aggregate_version
        assert version_after_patch == version_after_post + 1

        # DELETE bumps.
        await client.delete(
            f"/api/v1/admin/properties/{property_id}/pois/{poi_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        version_after_delete = (await property_repo.get_by_id(UUID(property_id))).aggregate_version
        assert version_after_delete == version_after_patch + 1


class TestEnrichProperty:
    """Integration tests for the auto-discovery trigger.

    These hit the enqueue endpoint only — the actual workflow runs in
    the worker, which is unit-tested separately. We assert the command
    arrives on the in-memory command publisher with the right payload.
    """

    async def _create_property_with_coords(
        self,
        client,
        auth_headers,
        property_repo,
        latitude: float | None = 38.768,
        longitude: float | None = -9.108,
    ) -> str:
        property_id = await _create_property(client, auth_headers)
        # CreatePropertyRequest doesn't accept lat/lng; set directly on the
        # in-memory repo. Production sets coords via amenity-discovery /
        # geocoding flows that run elsewhere.
        prop = await property_repo.get_by_id(UUID(property_id))
        prop.latitude = latitude
        prop.longitude = longitude
        await property_repo.save(prop)
        return property_id

    async def test_enrich_happy_path_returns_202_and_queues_command(
        self, client, auth_headers, property_repo, command_publisher
    ):
        property_id = await self._create_property_with_coords(client, auth_headers, property_repo)

        response = await client.post(
            f"/api/v1/admin/properties/{property_id}/enrich?organization_id={TEST_ORGANIZATION_ID}",
            json={"force": False},
            headers=auth_headers,
        )
        assert response.status_code == 202
        assert response.json() == {
            "status": "enrichment_queued",
            "property_id": property_id,
        }

        assert len(command_publisher.sent) == 1
        queue_url, event = command_publisher.sent[0]
        assert event.event_type == ENRICH_PROPERTY_REQUESTED_V1
        assert event.data["property_id"] == property_id
        assert event.data["organization_id"] == TEST_ORGANIZATION_ID
        assert event.data["force"] is False
        assert "requested_by_user_id" in event.data

    async def test_enrich_with_force_propagates_to_payload(
        self, client, auth_headers, property_repo, command_publisher
    ):
        property_id = await self._create_property_with_coords(client, auth_headers, property_repo)

        response = await client.post(
            f"/api/v1/admin/properties/{property_id}/enrich?organization_id={TEST_ORGANIZATION_ID}",
            json={"force": True},
            headers=auth_headers,
        )
        assert response.status_code == 202
        assert command_publisher.sent[0][1].data["force"] is True

    async def test_enrich_unknown_property_returns_404(
        self, client, auth_headers, command_publisher
    ):
        bogus_id = "00000000-0000-0000-0000-0000000000ff"
        response = await client.post(
            f"/api/v1/admin/properties/{bogus_id}/enrich?organization_id={TEST_ORGANIZATION_ID}",
            json={"force": False},
            headers=auth_headers,
        )
        assert response.status_code == 404
        assert command_publisher.sent == []

    async def test_enrich_missing_coordinates_returns_422(
        self, client, auth_headers, property_repo, command_publisher
    ):
        property_id = await self._create_property_with_coords(
            client, auth_headers, property_repo, latitude=None, longitude=None
        )
        response = await client.post(
            f"/api/v1/admin/properties/{property_id}/enrich?organization_id={TEST_ORGANIZATION_ID}",
            json={"force": False},
            headers=auth_headers,
        )
        assert response.status_code == 422
        assert command_publisher.sent == []

    async def test_enrich_cross_org_returns_403(
        self, client, auth_headers, property_repo, command_publisher
    ):
        property_id = await self._create_property_with_coords(client, auth_headers, property_repo)
        response = await client.post(
            f"/api/v1/admin/properties/{property_id}/enrich?organization_id={OTHER_ORGANIZATION_ID}",
            json={"force": False},
            headers=auth_headers,
        )
        assert response.status_code == 403
        assert command_publisher.sent == []

    async def test_enrich_unauthenticated_returns_401(
        self, client, property_repo, auth_headers, command_publisher
    ):
        property_id = await self._create_property_with_coords(client, auth_headers, property_repo)
        # auth_headers used only to seed the property; the actual enrich
        # call below has no Authorization header.
        response = await client.post(
            f"/api/v1/admin/properties/{property_id}/enrich?organization_id={TEST_ORGANIZATION_ID}",
            json={"force": False},
        )
        assert response.status_code == 401
        assert command_publisher.sent == []
