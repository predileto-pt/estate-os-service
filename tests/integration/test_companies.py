import pytest

from tests.conftest import make_test_token


async def _register_user(client, auth_headers):
    response = await client.post(
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
    return response.json()


@pytest.mark.asyncio
async def test_get_company(client, auth_headers):
    user = await _register_user(client, auth_headers)
    company_id = user["company_id"]
    response = await client.get(f"/api/v1/companies/{company_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Imobiliária Silva"


@pytest.mark.asyncio
async def test_get_other_company_forbidden(client, auth_headers):
    await _register_user(client, auth_headers)
    # Use a random UUID that isn't the user's company
    response = await client.get(
        "/api/v1/companies/00000000-0000-0000-0000-000000000000", headers=auth_headers
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_company(client, auth_headers):
    user = await _register_user(client, auth_headers)
    company_id = user["company_id"]
    response = await client.patch(
        f"/api/v1/companies/{company_id}",
        json={"name": "Nova Imobiliária", "tax_id_number": "987654321"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Nova Imobiliária"
    assert data["tax_id_number"] == "987654321"
