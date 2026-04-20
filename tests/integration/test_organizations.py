import pytest


async def _register_user(client, auth_headers):
    response = await client.post(
        "/api/v1/admin/auth/register",
        json={
            "name": "João Silva",
            "email": "joao@agency.pt",
            "organization_name": "Imobiliária Silva",
        },
        headers=auth_headers,
    )
    return response.json()


@pytest.mark.asyncio
async def test_get_organization(client, auth_headers):
    user = await _register_user(client, auth_headers)
    organization_id = user["organization"]["id"]
    response = await client.get(
        f"/api/v1/admin/organizations/{organization_id}", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Imobiliária Silva"


@pytest.mark.asyncio
async def test_get_other_organization_forbidden(client, auth_headers):
    await _register_user(client, auth_headers)
    # Use a random UUID that isn't the user's organization
    response = await client.get(
        "/api/v1/admin/organizations/00000000-0000-0000-0000-000000000000", headers=auth_headers
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_organization(client, auth_headers):
    user = await _register_user(client, auth_headers)
    organization_id = user["organization"]["id"]
    response = await client.patch(
        f"/api/v1/admin/organizations/{organization_id}",
        json={"name": "Nova Imobiliária", "nif": "987654321"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Nova Imobiliária"
    assert data["nif"] == "987654321"
