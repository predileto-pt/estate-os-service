import pytest


async def _register_user(client, auth_headers):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Discovery Owner",
            "email": "discovery@e2e-test.pt",
            "organization_name": "E2E Discovery",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    return response.json()


async def _create_property(client, auth_headers, org_id):
    response = await client.post(
        "/api/v1/properties/",
        json={
            "organization_id": org_id,
            "address": "Rua Augusta 100, 1100-053 Lisboa",
            "listing_type": "sale",
            "typology": "apartment",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.e2e
async def test_get_amenities_empty(client, auth_headers):
    user_data = await _register_user(client, auth_headers)
    org_id = user_data["organization_id"]
    prop = await _create_property(client, auth_headers, org_id)

    resp = await client.get(
        f"/api/v1/property-amenities/?property_id={prop['id']}&organization_id={org_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.e2e
async def test_get_amenities_not_authorized(client, auth_headers):
    user_data = await _register_user(client, auth_headers)
    org_id = user_data["organization_id"]
    prop = await _create_property(client, auth_headers, org_id)

    other_org_id = "00000000-0000-0000-0000-000000000099"
    resp = await client.get(
        f"/api/v1/property-amenities/?property_id={prop['id']}&organization_id={other_org_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.e2e
async def test_discover_amenities_missing_coordinates(client, auth_headers):
    user_data = await _register_user(client, auth_headers)
    org_id = user_data["organization_id"]
    prop = await _create_property(client, auth_headers, org_id)

    resp = await client.post(
        f"/api/v1/property-amenities/discover?property_id={prop['id']}&organization_id={org_id}",
        headers=auth_headers,
    )
    # Property created without coordinates should return 422
    assert resp.status_code == 422
    assert "coordinates" in resp.json()["detail"].lower()


@pytest.mark.e2e
async def test_discover_amenities_requires_auth(client):
    resp = await client.post(
        "/api/v1/property-amenities/discover?property_id=00000000-0000-0000-0000-000000000001&organization_id=00000000-0000-0000-0000-000000000001",
    )
    assert resp.status_code == 401
