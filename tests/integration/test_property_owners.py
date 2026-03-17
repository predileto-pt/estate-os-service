from tests.conftest import TEST_ORGANIZATION_ID

OTHER_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000099"


async def _create_property(client, auth_headers) -> str:
    resp = await client.post(
        "/api/v1/properties/",
        json={
            "organization_id": TEST_ORGANIZATION_ID,
            "address": "Rua das Flores 123",
            "listing_type": "sale",
            "typology": "apartment",
        },
        headers=auth_headers,
    )
    return resp.json()["id"]


OWNER_PAYLOAD = {
    "full_name": "Maria Silva Santos",
    "civil_status": "married",
    "address": "Rua das Flores 123, 4000-001 Porto",
    "nif": "123456789",
    "document_type": "cartao_cidadao",
    "document_id": "12345678",
    "issued_by": "Servicos de Identificacao Civil de Porto",
    "issuing_district": "Porto",
    "date_of_birth": "1985-06-15",
}


class TestCreatePropertyOwner:
    async def test_create_property_owner(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        payload = {
            **OWNER_PAYLOAD,
            "organization_id": TEST_ORGANIZATION_ID,
            "property_id": property_id,
        }

        response = await client.post("/api/v1/property-owners/", json=payload, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        # Response is now the full property with owners
        assert data["id"] == property_id
        assert len(data["owners"]) == 1
        assert data["owners"][0]["full_name"] == "Maria Silva Santos"
        assert data["owners"][0]["nif"] == "123456789"

    async def test_create_property_owner_invalid_nif(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        payload = {
            **OWNER_PAYLOAD,
            "organization_id": TEST_ORGANIZATION_ID,
            "property_id": property_id,
            "nif": "12345",
        }

        response = await client.post("/api/v1/property-owners/", json=payload, headers=auth_headers)
        assert response.status_code == 422

    async def test_create_property_owner_property_not_found(self, client, auth_headers):
        payload = {
            **OWNER_PAYLOAD,
            "organization_id": TEST_ORGANIZATION_ID,
            "property_id": "00000000-0000-0000-0000-000000000099",
        }
        response = await client.post("/api/v1/property-owners/", json=payload, headers=auth_headers)
        assert response.status_code == 404

    async def test_create_property_owner_not_authorized(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        payload = {
            **OWNER_PAYLOAD,
            "organization_id": OTHER_ORGANIZATION_ID,
            "property_id": property_id,
        }

        response = await client.post("/api/v1/property-owners/", json=payload, headers=auth_headers)
        assert response.status_code == 403

    async def test_create_multiple_owners(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)

        for name in ["Owner 1", "Owner 2"]:
            payload = {
                **OWNER_PAYLOAD,
                "organization_id": TEST_ORGANIZATION_ID,
                "property_id": property_id,
                "full_name": name,
            }
            response = await client.post(
                "/api/v1/property-owners/", json=payload, headers=auth_headers
            )
            assert response.status_code == 201

        # Verify both owners are on the property
        prop_resp = await client.get(
            f"/api/v1/properties/{property_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert len(prop_resp.json()["owners"]) == 2


class TestExtractFromDocument:
    async def test_extract_from_document(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)

        response = await client.post(
            "/api/v1/property-owners/extract-from-document",
            data={"property_id": property_id, "organization_id": TEST_ORGANIZATION_ID},
            files={"file": ("doc.jpg", b"fake-image-data", "image/jpeg")},
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        # Response is now the full property with owners
        assert data["id"] == property_id
        assert len(data["owners"]) == 1
        assert data["owners"][0]["full_name"] == "Maria Silva Santos"
        assert data["owners"][0]["nif"] == "123456789"

    async def test_extract_from_document_not_authorized(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)

        response = await client.post(
            "/api/v1/property-owners/extract-from-document",
            data={"property_id": property_id, "organization_id": OTHER_ORGANIZATION_ID},
            files={"file": ("doc.jpg", b"fake-image-data", "image/jpeg")},
            headers=auth_headers,
        )
        assert response.status_code == 403


class TestListPropertyOwners:
    async def test_list_property_owners(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)

        # Create two owners
        for name in ["Owner 1", "Owner 2"]:
            payload = {
                **OWNER_PAYLOAD,
                "organization_id": TEST_ORGANIZATION_ID,
                "property_id": property_id,
                "full_name": name,
            }
            await client.post("/api/v1/property-owners/", json=payload, headers=auth_headers)

        response = await client.get(
            f"/api/v1/property-owners/?property_id={property_id}&organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_list_property_owners_not_authorized(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)

        response = await client.get(
            f"/api/v1/property-owners/?property_id={property_id}&organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403


class TestGetPropertyOwner:
    async def test_get_property_owner(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        payload = {
            **OWNER_PAYLOAD,
            "organization_id": TEST_ORGANIZATION_ID,
            "property_id": property_id,
        }
        create_resp = await client.post(
            "/api/v1/property-owners/", json=payload, headers=auth_headers
        )
        owner_id = create_resp.json()["owners"][0]["id"]

        response = await client.get(
            f"/api/v1/property-owners/{owner_id}?property_id={property_id}&organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == owner_id

    async def test_get_property_owner_not_found(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        response = await client.get(
            f"/api/v1/property-owners/00000000-0000-0000-0000-000000000099?property_id={property_id}&organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_get_property_owner_not_authorized(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        payload = {
            **OWNER_PAYLOAD,
            "organization_id": TEST_ORGANIZATION_ID,
            "property_id": property_id,
        }
        create_resp = await client.post(
            "/api/v1/property-owners/", json=payload, headers=auth_headers
        )
        owner_id = create_resp.json()["owners"][0]["id"]

        response = await client.get(
            f"/api/v1/property-owners/{owner_id}?property_id={property_id}&organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403
