from tests.conftest import TEST_ORGANIZATION_ID

OTHER_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000099"


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


class TestCreatePropertyPrice:
    async def test_create_property_price(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        payload = {
            "organization_id": TEST_ORGANIZATION_ID,
            "property_id": property_id,
            "amount": "250000.00",
            "listing_type": "sale",
        }

        response = await client.post("/api/v1/admin/property-prices/", json=payload, headers=auth_headers)
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == property_id
        assert len(data["prices"]) == 1
        assert data["prices"][0]["amount"] == "250000.00"
        assert data["prices"][0]["listing_type"] == "sale"

    async def test_create_property_price_invalid_amount(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        payload = {
            "organization_id": TEST_ORGANIZATION_ID,
            "property_id": property_id,
            "amount": "-100",
            "listing_type": "sale",
        }

        response = await client.post("/api/v1/admin/property-prices/", json=payload, headers=auth_headers)
        assert response.status_code == 422

    async def test_create_property_price_zero_amount(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        payload = {
            "organization_id": TEST_ORGANIZATION_ID,
            "property_id": property_id,
            "amount": "0",
            "listing_type": "sale",
        }

        response = await client.post("/api/v1/admin/property-prices/", json=payload, headers=auth_headers)
        assert response.status_code == 422

    async def test_create_property_price_property_not_found(self, client, auth_headers):
        payload = {
            "organization_id": TEST_ORGANIZATION_ID,
            "property_id": "00000000-0000-0000-0000-000000000099",
            "amount": "250000.00",
            "listing_type": "sale",
        }
        response = await client.post("/api/v1/admin/property-prices/", json=payload, headers=auth_headers)
        assert response.status_code == 404

    async def test_create_property_price_not_authorized(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)
        payload = {
            "organization_id": OTHER_ORGANIZATION_ID,
            "property_id": property_id,
            "amount": "250000.00",
            "listing_type": "sale",
        }

        response = await client.post("/api/v1/admin/property-prices/", json=payload, headers=auth_headers)
        assert response.status_code == 403


class TestListPropertyPrices:
    async def test_list_property_prices(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)

        # Create two prices
        for amount in ["250000.00", "260000.00"]:
            payload = {
                "organization_id": TEST_ORGANIZATION_ID,
                "property_id": property_id,
                "amount": amount,
                "listing_type": "sale",
            }
            await client.post("/api/v1/admin/property-prices/", json=payload, headers=auth_headers)

        response = await client.get(
            f"/api/v1/admin/property-prices/?property_id={property_id}&organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_list_property_prices_not_authorized(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)

        response = await client.get(
            f"/api/v1/admin/property-prices/?property_id={property_id}&organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403

    async def test_prices_in_property_get_response(self, client, auth_headers):
        property_id = await _create_property(client, auth_headers)

        # Create a price
        await client.post(
            "/api/v1/admin/property-prices/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "property_id": property_id,
                "amount": "350000.00",
                "listing_type": "sale",
            },
            headers=auth_headers,
        )

        # Get property and verify prices are included
        response = await client.get(
            f"/api/v1/admin/properties/{property_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["prices"]) == 1
        assert data["prices"][0]["amount"] == "350000.00"
