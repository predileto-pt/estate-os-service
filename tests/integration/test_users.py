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
async def test_get_user_profile(client, auth_headers):
    await _register_user(client, auth_headers)
    response = await client.get("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["email"] == "joao@agency.pt"
    assert data["company"]["name"] == "Imobiliária Silva"


@pytest.mark.asyncio
async def test_update_user_profile(client, auth_headers):
    await _register_user(client, auth_headers)
    response = await client.patch(
        "/api/v1/users/me",
        json={"name": "João Santos", "phone_country_code": "+34", "phone_number": "612345678"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "João Santos"
    assert data["phone"]["country_code"] == "+34"


@pytest.mark.asyncio
async def test_update_user_name_only(client, auth_headers):
    await _register_user(client, auth_headers)
    response = await client.patch(
        "/api/v1/users/me",
        json={"name": "New Name"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"
