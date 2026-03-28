import pytest

from tests.e2e.conftest import TEST_SUPABASE_USER_ID


@pytest.mark.e2e
async def test_register_creates_user_org_subscription_membership(client, auth_headers):
    response = await client.post(
        "/api/v1/admin/auth/register",
        json={
            "name": "João Silva",
            "email": "joao@e2e-test.pt",
            "organization_name": "Imobiliária E2E",
            "phone_country_code": "+351",
            "phone_number": "912345678",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()

    assert data["email"] == "joao@e2e-test.pt"
    assert data["name"] == "João Silva"
    assert data["supabase_user_id"] == TEST_SUPABASE_USER_ID

    # Verify /me returns the full profile with organization + membership role
    me_response = await client.get("/api/v1/admin/auth/me", headers=auth_headers)
    assert me_response.status_code == 200
    me_data = me_response.json()

    assert me_data["user"]["email"] == "joao@e2e-test.pt"
    assert me_data["organization"]["name"] == "Imobiliária E2E"
    assert me_data["role"] == "owner"


@pytest.mark.e2e
async def test_register_duplicate_returns_409(client, auth_headers):
    payload = {
        "name": "João Silva",
        "email": "joao-dup@e2e-test.pt",
        "organization_name": "Imobiliária E2E",
    }
    response1 = await client.post("/api/v1/admin/auth/register", json=payload, headers=auth_headers)
    assert response1.status_code == 200

    response2 = await client.post("/api/v1/admin/auth/register", json=payload, headers=auth_headers)
    assert response2.status_code == 409
