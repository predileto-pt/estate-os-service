from tests.conftest import TEST_ORGANIZATION_ID

OTHER_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000099"


class TestCreateProperty:
    async def test_create_property(self, client, auth_headers):
        response = await client.post(
            "/api/v1/properties/",
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
        assert data["owners"] == []

    async def test_create_property_without_description(self, client, auth_headers):
        response = await client.post(
            "/api/v1/properties/",
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
            "/api/v1/properties/",
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
            "/api/v1/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 1",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 2",
                "listing_type": "purchase",
                "typology": "house",
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/v1/properties/?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_list_properties_empty(self, client, auth_headers):
        response = await client.get(
            f"/api/v1/properties/?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_properties_only_own_org(self, client, auth_headers):
        # Create property for default org
        await client.post(
            "/api/v1/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 1",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )

        # List for different org
        response = await client.get(
            f"/api/v1/properties/?organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json() == []


class TestGetProperty:
    async def test_get_property(self, client, auth_headers):
        create_resp = await client.post(
            "/api/v1/properties/",
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
            f"/api/v1/properties/{property_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == property_id
        assert response.json()["owners"] == []

    async def test_get_property_not_found(self, client, auth_headers):
        response = await client.get(
            f"/api/v1/properties/00000000-0000-0000-0000-000000000099?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_get_property_not_authorized(self, client, auth_headers):
        create_resp = await client.post(
            "/api/v1/properties/",
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
            f"/api/v1/properties/{property_id}?organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403

    async def test_get_property_with_owners(self, client, auth_headers):
        create_resp = await client.post(
            "/api/v1/properties/",
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
            "/api/v1/property-owners/",
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
            f"/api/v1/properties/{property_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["owners"]) == 1
        assert data["owners"][0]["full_name"] == "Maria Silva"
