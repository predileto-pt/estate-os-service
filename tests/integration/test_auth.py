import pytest

from tests.conftest import TEST_SUPABASE_USER_ID, make_test_token


@pytest.mark.asyncio
async def test_register(client, auth_headers):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "João Silva",
            "email": "joao@agency.pt",
            "company_name": "Imobiliária Silva",
            "tax_id_number": "123456789",
            "address_street": "Rua Augusta 1",
            "address_country": "PT",
            "phone_country_code": "+351",
            "phone_number": "912345678",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "joao@agency.pt"
    assert data["name"] == "João Silva"
    assert data["phone"]["country_code"] == "+351"
    assert data["supabase_user_id"] == TEST_SUPABASE_USER_ID


@pytest.mark.asyncio
async def test_register_duplicate(client, auth_headers):
    payload = {
        "name": "João Silva",
        "email": "joao@agency.pt",
        "company_name": "Imobiliária Silva",
        "tax_id_number": "123456789",
        "address_street": "Rua Augusta 1",
        "address_country": "PT",
    }
    await client.post("/api/v1/auth/register", json=payload, headers=auth_headers)
    response = await client.post("/api/v1/auth/register", json=payload, headers=auth_headers)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_get_me(client, auth_headers):
    # First register
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
    # Then get me
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["email"] == "joao@agency.pt"
    assert data["company"]["name"] == "Imobiliária Silva"


@pytest.mark.asyncio
async def test_get_me_not_registered(client, auth_headers):
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_no_auth_header(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token(client):
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer invalid-token"}
    )
    assert response.status_code == 401
