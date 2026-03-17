import pytest

from tests.conftest import TEST_SUPABASE_USER_ID


@pytest.mark.asyncio
async def test_register(client, auth_headers):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "João Silva",
            "email": "joao@agency.pt",
            "organization_name": "Imobiliária Silva",
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
async def test_register_creates_membership(client, auth_headers, membership_repo):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "João Silva",
            "email": "joao@agency.pt",
            "organization_name": "Imobiliária Silva",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    from uuid import UUID

    user_id = UUID(data["id"])
    memberships = await membership_repo.list_by_user(user_id)
    assert len(memberships) == 1
    assert memberships[0].role.value == "owner"


@pytest.mark.asyncio
async def test_register_duplicate(client, auth_headers):
    payload = {
        "name": "João Silva",
        "email": "joao@agency.pt",
        "organization_name": "Imobiliária Silva",
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
            "organization_name": "Imobiliária Silva",
        },
        headers=auth_headers,
    )
    # Then get me
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["email"] == "joao@agency.pt"
    assert data["organization"]["name"] == "Imobiliária Silva"
    assert data["role"] == "owner"


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
