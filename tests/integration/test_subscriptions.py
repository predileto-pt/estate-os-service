import pytest


async def _register_user(client, auth_headers):
    await client.post(
        "/api/v1/auth/register",
        json={
            "name": "João Silva",
            "email": "joao@agency.pt",
            "company_name": "Imobiliária Silva",
            "tax_id_number": "123456789",
            "address_street": "Rua Augusta 1",
            "address_country": "PT",
        },
        headers=auth_headers,
    )


@pytest.mark.asyncio
async def test_list_plans(client):
    response = await client.get("/api/v1/subscriptions/plans")
    assert response.status_code == 200
    plans = response.json()
    assert len(plans) == 3
    assert plans[0]["name"] == "freemium"


@pytest.mark.asyncio
async def test_get_current_subscription(client, auth_headers):
    await _register_user(client, auth_headers)
    response = await client.get("/api/v1/subscriptions/current", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["plan"] == "freemium"
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_create_subscription(client, auth_headers):
    await _register_user(client, auth_headers)
    response = await client.post(
        "/api/v1/subscriptions",
        json={"plan": "pro", "type": "stripe", "status": "active"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["plan"] == "pro"
    assert data["type"] == "stripe"


@pytest.mark.asyncio
async def test_update_subscription(client, auth_headers):
    await _register_user(client, auth_headers)
    # Create a subscription first
    create_resp = await client.post(
        "/api/v1/subscriptions",
        json={"plan": "pro", "type": "stripe"},
        headers=auth_headers,
    )
    sub_id = create_resp.json()["id"]

    response = await client.patch(
        f"/api/v1/subscriptions/{sub_id}",
        json={"status": "cancelled"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_invalid_plan(client, auth_headers):
    await _register_user(client, auth_headers)
    response = await client.post(
        "/api/v1/subscriptions",
        json={"plan": "invalid", "type": "stripe"},
        headers=auth_headers,
    )
    assert response.status_code == 422
