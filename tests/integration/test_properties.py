from uuid import UUID

import pytest

from tests.conftest import TEST_ORGANIZATION_ID
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)

OTHER_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture(autouse=True)
def _auto_seed_member(seed_test_member):
    # Applies to every test in this module so property routes can resolve
    # the JWT's `sub` to a domain User+Membership in TEST_ORGANIZATION_ID.
    return seed_test_member


class TestCreateProperty:
    async def test_create_property(self, client, auth_headers):
        response = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Rua das Flores 123, Porto",
                "listing_type": "sale",
                "typology": "apartment",
                "description": "Beautiful apartment",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["address"] == "Rua das Flores 123, Porto"
        assert data["listing_type"] == "sale"
        assert data["typology"] == "apartment"
        assert data["status"] == "draft"
        assert data["description"] == "Beautiful apartment"
        assert data["organization_id"] == TEST_ORGANIZATION_ID
        assert data["latitude"] is None
        assert data["longitude"] is None
        assert data["owners"] == []
        assert data["prices"] == []

    async def test_create_property_without_description(self, client, auth_headers):
        response = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Rua do Exemplo, Lisboa",
                "listing_type": "purchase",
                "typology": "house",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["description"] is None

    async def test_create_property_unauthenticated(self, client):
        response = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Rua das Flores 123",
                "listing_type": "sale",
                "typology": "apartment",
            },
        )
        assert response.status_code == 401


class TestListProperties:
    async def test_list_properties(self, client, auth_headers):
        # Create two properties
        await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 1",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 2",
                "listing_type": "purchase",
                "typology": "house",
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/v1/admin/properties/?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_list_properties_empty(self, client, auth_headers):
        response = await client.get(
            f"/api/v1/admin/properties/?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_properties_other_org_forbidden(self, client, auth_headers):
        # Create property for default org
        await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 1",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )

        # Listing for an org the caller isn't a member of is now forbidden,
        # not an empty success — the membership check runs before the handler.
        response = await client.get(
            f"/api/v1/admin/properties/?organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403


class TestListPropertiesSummary:
    async def test_list_properties_summary(self, client, auth_headers):
        # Create a property
        create_resp = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Rua das Flores 123, Porto",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        property_id = create_resp.json()["id"]

        # Add an owner
        await client.post(
            "/api/v1/admin/property-owners/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "property_id": property_id,
                "full_name": "Maria Silva",
                "civil_status": "single",
                "address": "Rua do Exemplo 1",
                "nif": "123456789",
                "document_type": "cartao_cidadao",
                "document_id": "12345678",
                "issued_by": "SEF",
                "date_of_birth": "1990-01-01",
            },
            headers=auth_headers,
        )

        # Add a price
        await client.post(
            "/api/v1/admin/property-prices/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "property_id": property_id,
                "amount": "250000.00",
                "listing_type": "sale",
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/v1/admin/properties/summary?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == property_id
        assert data[0]["address"] == "Rua das Flores 123, Porto"
        assert data[0]["listing_type"] == "sale"
        assert data[0]["typology"] == "apartment"
        assert data[0]["price"] == "250000.00"
        assert data[0]["owners"] == [{"full_name": "Maria Silva"}]
        # Should NOT contain full property fields
        assert "prices" not in data[0]
        assert "characteristics" not in data[0]

    async def test_list_properties_summary_no_price(self, client, auth_headers):
        # Property with no prices should return price as None
        await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Rua Sem Preço 1",
                "listing_type": "purchase",
                "typology": "house",
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/v1/admin/properties/summary?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["listing_type"] == "purchase"
        assert data[0]["typology"] == "house"
        assert data[0]["price"] is None
        assert data[0]["owners"] == []

    async def test_list_properties_summary_empty(self, client, auth_headers):
        response = await client.get(
            f"/api/v1/admin/properties/summary?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json() == []


class TestGetProperty:
    async def test_get_property(self, client, auth_headers):
        create_resp = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 1",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        property_id = create_resp.json()["id"]

        response = await client.get(
            f"/api/v1/admin/properties/{property_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == property_id
        assert response.json()["owners"] == []
        assert response.json()["prices"] == []

    async def test_get_property_not_found(self, client, auth_headers):
        response = await client.get(
            f"/api/v1/admin/properties/00000000-0000-0000-0000-000000000099?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_get_property_not_authorized(self, client, auth_headers):
        create_resp = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 1",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        property_id = create_resp.json()["id"]

        # Try to get with wrong organization
        response = await client.get(
            f"/api/v1/admin/properties/{property_id}?organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403

    async def test_get_property_with_owners(self, client, auth_headers):
        create_resp = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 1",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        property_id = create_resp.json()["id"]

        # Add an owner
        await client.post(
            "/api/v1/admin/property-owners/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "property_id": property_id,
                "full_name": "Maria Silva",
                "civil_status": "single",
                "address": "Rua do Exemplo 1",
                "nif": "123456789",
                "document_type": "cartao_cidadao",
                "document_id": "12345678",
                "issued_by": "SEF",
                "date_of_birth": "1990-01-01",
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/v1/admin/properties/{property_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["owners"]) == 1
        assert data["owners"][0]["full_name"] == "Maria Silva"


def _make_property(
    *, status: PropertyStatus = PropertyStatus.ACTIVE, address: str = "Addr"
) -> Property:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return Property(
        id=UUID("00000000-0000-0000-0000-" + f"{id(address):012d}"[-12:]),
        organization_id=UUID(TEST_ORGANIZATION_ID),
        address=address,
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=status,
        description=None,
        created_at=now,
        updated_at=now,
    )


class TestListActiveProperties:
    async def test_list_active_properties(self, client, property_repo):
        active = _make_property(status=PropertyStatus.ACTIVE, address="Active 1")
        draft = _make_property(status=PropertyStatus.DRAFT, address="Draft 1")
        sold = _make_property(status=PropertyStatus.SOLD, address="Sold 1")
        await property_repo.save(active)
        await property_repo.save(draft)
        await property_repo.save(sold)

        response = await client.get("/api/v1/admin/properties/active")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["address"] == "Active 1"
        assert data[0]["status"] == "active"
        assert "owners" not in data[0]

    async def test_list_active_properties_empty(self, client):
        response = await client.get("/api/v1/admin/properties/active")
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_active_properties_no_auth_required(self, client, property_repo):
        active = _make_property(status=PropertyStatus.ACTIVE, address="Public 1")
        await property_repo.save(active)

        # No auth headers — should still succeed
        response = await client.get("/api/v1/admin/properties/active")
        assert response.status_code == 200
        assert len(response.json()) == 1
