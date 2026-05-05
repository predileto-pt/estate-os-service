from uuid import UUID

import pytest

from tests.conftest import TEST_ORGANIZATION_ID
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)

OTHER_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture(autouse=True)
def _auto_seed_member(seed_test_member):
    # Applies to every test in this module so property routes can resolve
    # the JWT's `sub` to a domain User+Membership in TEST_ORGANIZATION_ID.
    return seed_test_member


class TestCreateProperty:
    async def test_create_property(self, client, auth_headers):
        response = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Rua das Flores 123, Porto",
                "listing_type": "sale",
                "typology": "apartment",
                "description": "Beautiful apartment",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["address"] == "Rua das Flores 123, Porto"
        assert data["listing_type"] == "sale"
        assert data["typology"] == "apartment"
        assert data["status"] == "draft"
        assert data["description"] == "Beautiful apartment"
        assert data["organization_id"] == TEST_ORGANIZATION_ID
        assert data["latitude"] is None
        assert data["longitude"] is None
        assert data["owners"] == []
        assert data["prices"] == []

    async def test_create_property_without_description(self, client, auth_headers):
        response = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Rua do Exemplo, Lisboa",
                "listing_type": "purchase",
                "typology": "house",
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["description"] is None

    async def test_create_property_unauthenticated(self, client):
        response = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Rua das Flores 123",
                "listing_type": "sale",
                "typology": "apartment",
            },
        )
        assert response.status_code == 401


class TestListProperties:
    async def test_list_properties(self, client, auth_headers):
        # Create two properties
        await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 1",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 2",
                "listing_type": "purchase",
                "typology": "house",
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/v1/admin/properties/?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_list_properties_empty(self, client, auth_headers):
        response = await client.get(
            f"/api/v1/admin/properties/?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_properties_other_org_forbidden(self, client, auth_headers):
        # Create property for default org
        await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 1",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )

        # Listing for an org the caller isn't a member of is now forbidden,
        # not an empty success — the membership check runs before the handler.
        response = await client.get(
            f"/api/v1/admin/properties/?organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403


class TestListPropertiesSummary:
    async def test_list_properties_summary(self, client, auth_headers):
        # Create a property
        create_resp = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Rua das Flores 123, Porto",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        property_id = create_resp.json()["id"]

        # Add an owner
        await client.post(
            "/api/v1/admin/property-owners/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "property_id": property_id,
                "full_name": "Maria Silva",
                "civil_status": "single",
                "address": "Rua do Exemplo 1",
                "nif": "123456789",
                "document_type": "cartao_cidadao",
                "document_id": "12345678",
                "issued_by": "SEF",
                "date_of_birth": "1990-01-01",
            },
            headers=auth_headers,
        )

        # Add a price
        await client.post(
            "/api/v1/admin/property-prices/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "property_id": property_id,
                "amount": "250000.00",
                "listing_type": "sale",
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/v1/admin/properties/summary?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == property_id
        assert data[0]["address"] == "Rua das Flores 123, Porto"
        assert data[0]["listing_type"] == "sale"
        assert data[0]["typology"] == "apartment"
        assert data[0]["price"] == "250000.00"
        assert data[0]["owners"] == [{"full_name": "Maria Silva"}]
        # Should NOT contain full property fields
        assert "prices" not in data[0]
        assert "characteristics" not in data[0]

    async def test_list_properties_summary_no_price(self, client, auth_headers):
        # Property with no prices should return price as None
        await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Rua Sem Preço 1",
                "listing_type": "purchase",
                "typology": "house",
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/v1/admin/properties/summary?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["listing_type"] == "purchase"
        assert data[0]["typology"] == "house"
        assert data[0]["price"] is None
        assert data[0]["owners"] == []

    async def test_list_properties_summary_empty(self, client, auth_headers):
        response = await client.get(
            f"/api/v1/admin/properties/summary?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json() == []


class TestGetProperty:
    async def test_get_property(self, client, auth_headers):
        create_resp = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 1",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        property_id = create_resp.json()["id"]

        response = await client.get(
            f"/api/v1/admin/properties/{property_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == property_id
        assert response.json()["owners"] == []
        assert response.json()["prices"] == []

    async def test_get_property_not_found(self, client, auth_headers):
        response = await client.get(
            f"/api/v1/admin/properties/00000000-0000-0000-0000-000000000099?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_get_property_not_authorized(self, client, auth_headers):
        create_resp = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 1",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        property_id = create_resp.json()["id"]

        # Try to get with wrong organization
        response = await client.get(
            f"/api/v1/admin/properties/{property_id}?organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403

    async def test_get_property_with_owners(self, client, auth_headers):
        create_resp = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": "Addr 1",
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        property_id = create_resp.json()["id"]

        # Add an owner
        await client.post(
            "/api/v1/admin/property-owners/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "property_id": property_id,
                "full_name": "Maria Silva",
                "civil_status": "single",
                "address": "Rua do Exemplo 1",
                "nif": "123456789",
                "document_type": "cartao_cidadao",
                "document_id": "12345678",
                "issued_by": "SEF",
                "date_of_birth": "1990-01-01",
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/v1/admin/properties/{property_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["owners"]) == 1
        assert data["owners"][0]["full_name"] == "Maria Silva"


def _make_property(
    *, status: PropertyStatus = PropertyStatus.ACTIVE, address: str = "Addr"
) -> Property:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return Property(
        id=UUID("00000000-0000-0000-0000-" + f"{id(address):012d}"[-12:]),
        organization_id=UUID(TEST_ORGANIZATION_ID),
        address=address,
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=status,
        description=None,
        created_at=now,
        updated_at=now,
    )


def _make_publishable_property(
    *, status: PropertyStatus = PropertyStatus.DRAFT, address: str = "Pub Addr"
) -> Property:
    """Property that satisfies every publishability precondition —
    owner + price + image + address."""
    from datetime import datetime, timezone
    from decimal import Decimal
    from uuid import uuid4

    from properties.domain.models.property_image import PropertyImage
    from properties.domain.models.property_owner import PropertyOwner
    from properties.domain.models.property_price import PropertyPrice

    now = datetime.now(timezone.utc)
    prop = _make_property(status=status, address=address)
    prop.add_owner(
        PropertyOwner(
            id=uuid4(),
            property_id=prop.id,
            full_name="Maria Silva",
            civil_status=None,
            address=address,
            nif="123456789",
            document_type=None,
            document_id=None,
            issued_by=None,
            issuing_district=None,
            date_of_birth=None,
            created_at=now,
            updated_at=now,
        )
    )
    prop.add_price(
        PropertyPrice(
            id=uuid4(),
            property_id=prop.id,
            amount=Decimal("350000.00"),
            listing_type=ListingType.SALE,
            created_at=now,
            updated_at=now,
        )
    )
    prop.add_image(
        PropertyImage(
            id=uuid4(),
            property_id=prop.id,
            s3_key="photos/x.jpg",
            filename="x.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            display_order=0,
            created_at=now,
            updated_at=now,
        )
    )
    prop.bump_version()
    return prop


class TestPublishProperty:
    async def test_publish_happy_path_flips_to_active(self, client, auth_headers, property_repo):
        prop = _make_publishable_property()
        version_before = prop.aggregate_version  # snapshot; in-memory repo mutates in place
        await property_repo.save(prop)

        response = await client.post(
            f"/api/v1/admin/properties/{prop.id}/publish?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(prop.id)
        assert data["status"] == "active"

        # State landed in the repo too, with version bumped.
        stored = await property_repo.get_by_id(prop.id)
        assert stored.status == PropertyStatus.ACTIVE
        assert stored.aggregate_version == version_before + 1

    async def test_publish_appears_in_list_active(self, client, auth_headers, property_repo):
        """Draft becomes ACTIVE → public /active endpoint returns it."""
        prop = _make_publishable_property()
        await property_repo.save(prop)

        # Before publish: not visible
        before = await client.get("/api/v1/admin/properties/active")
        assert all(item["id"] != str(prop.id) for item in before.json())

        await client.post(
            f"/api/v1/admin/properties/{prop.id}/publish?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )

        after = await client.get("/api/v1/admin/properties/active")
        assert any(item["id"] == str(prop.id) for item in after.json())

    async def test_publish_incomplete_returns_422_with_reasons(
        self, client, auth_headers, property_repo
    ):
        prop = _make_property(status=PropertyStatus.DRAFT, address="Incomplete")
        # No owner, no price, no image.
        await property_repo.save(prop)

        response = await client.post(
            f"/api/v1/admin/properties/{prop.id}/publish?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["message"] == "Property is not publishable"
        assert set(detail["reasons"]) >= {"missing_price", "missing_owner", "missing_image"}

    async def test_republish_of_active_returns_422_status_reason(
        self, client, auth_headers, property_repo
    ):
        prop = _make_publishable_property(status=PropertyStatus.ACTIVE)
        await property_repo.save(prop)

        response = await client.post(
            f"/api/v1/admin/properties/{prop.id}/publish?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 422
        assert response.json()["detail"]["reasons"] == ["cannot_publish_from_status:active"]

    async def test_publish_unknown_id_returns_404(self, client, auth_headers):
        missing_id = UUID("00000000-0000-0000-0000-0000000000ff")
        response = await client.post(
            f"/api/v1/admin/properties/{missing_id}/publish?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_publish_wrong_org_returns_403_or_404(self, client, auth_headers, property_repo):
        """Cross-org publish attempt. require_org_member blocks at the
        membership layer (403) before we even reach the use case's
        load-and-compare check."""
        other_org_prop = _make_publishable_property()
        other_org_prop.organization_id = UUID(OTHER_ORGANIZATION_ID)
        await property_repo.save(other_org_prop)

        response = await client.post(
            f"/api/v1/admin/properties/{other_org_prop.id}/publish"
            f"?organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        # Caller is not a member of OTHER_ORGANIZATION_ID.
        assert response.status_code in (403, 404)

    async def test_publish_unauthenticated_returns_401(self, client, property_repo):
        prop = _make_publishable_property()
        await property_repo.save(prop)

        response = await client.post(
            f"/api/v1/admin/properties/{prop.id}/publish?organization_id={TEST_ORGANIZATION_ID}",
        )
        assert response.status_code == 401

    async def test_publish_non_admin_returns_403(
        self, client, auth_headers, property_repo, membership_repo
    ):
        """Demote the auto-seeded OWNER membership to MEMBER so the
        role-check in the route triggers."""
        from organizations.domain.models.membership import MembershipRole

        # Find and demote the test user's membership.
        memberships = await membership_repo.list_by_organization(UUID(TEST_ORGANIZATION_ID))
        target = next(m for m in memberships)
        target.role = MembershipRole.MEMBER
        await membership_repo.save(target)

        prop = _make_publishable_property()
        await property_repo.save(prop)

        response = await client.post(
            f"/api/v1/admin/properties/{prop.id}/publish?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403


class TestUpdatePropertyAddress:
    async def _create(self, client, auth_headers, address: str = "Rua Original 1"):
        resp = await client.post(
            "/api/v1/admin/properties/",
            json={
                "organization_id": TEST_ORGANIZATION_ID,
                "address": address,
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        return resp.json()["id"]

    async def test_update_address_happy_path(self, client, auth_headers, property_repo):
        property_id = await self._create(client, auth_headers, address="Rua Velha")
        version_before = (await property_repo.get_by_id(UUID(property_id))).aggregate_version

        response = await client.patch(
            f"/api/v1/admin/properties/{property_id}/address?organization_id={TEST_ORGANIZATION_ID}",
            json={"address": "Rua Nova 5, Porto"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["address"] == "Rua Nova 5, Porto"

        stored = await property_repo.get_by_id(UUID(property_id))
        assert stored.address == "Rua Nova 5, Porto"
        assert stored.aggregate_version == version_before + 1

    async def test_update_address_strips_whitespace(self, client, auth_headers, property_repo):
        property_id = await self._create(client, auth_headers)

        response = await client.patch(
            f"/api/v1/admin/properties/{property_id}/address?organization_id={TEST_ORGANIZATION_ID}",
            json={"address": "  Rua Nova  "},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["address"] == "Rua Nova"

        stored = await property_repo.get_by_id(UUID(property_id))
        assert stored.address == "Rua Nova"

    async def test_update_address_no_op_unchanged_value(self, client, auth_headers, property_repo):
        property_id = await self._create(client, auth_headers, address="Rua Igual")
        version_before = (await property_repo.get_by_id(UUID(property_id))).aggregate_version

        response = await client.patch(
            f"/api/v1/admin/properties/{property_id}/address?organization_id={TEST_ORGANIZATION_ID}",
            json={"address": "Rua Igual"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["address"] == "Rua Igual"

        stored = await property_repo.get_by_id(UUID(property_id))
        assert stored.aggregate_version == version_before

    async def test_update_address_no_op_whitespace_variant(
        self, client, auth_headers, property_repo
    ):
        property_id = await self._create(client, auth_headers, address="Rua Igual")
        version_before = (await property_repo.get_by_id(UUID(property_id))).aggregate_version

        response = await client.patch(
            f"/api/v1/admin/properties/{property_id}/address?organization_id={TEST_ORGANIZATION_ID}",
            json={"address": "  Rua Igual  "},
            headers=auth_headers,
        )
        assert response.status_code == 200

        stored = await property_repo.get_by_id(UUID(property_id))
        assert stored.aggregate_version == version_before

    async def test_update_address_empty_returns_422(self, client, auth_headers):
        property_id = await self._create(client, auth_headers)
        response = await client.patch(
            f"/api/v1/admin/properties/{property_id}/address?organization_id={TEST_ORGANIZATION_ID}",
            json={"address": ""},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_update_address_whitespace_only_returns_422(self, client, auth_headers):
        property_id = await self._create(client, auth_headers)
        response = await client.patch(
            f"/api/v1/admin/properties/{property_id}/address?organization_id={TEST_ORGANIZATION_ID}",
            json={"address": "   "},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_update_address_unknown_id_returns_404(self, client, auth_headers):
        missing = "00000000-0000-0000-0000-0000000000ff"
        response = await client.patch(
            f"/api/v1/admin/properties/{missing}/address?organization_id={TEST_ORGANIZATION_ID}",
            json={"address": "Rua Nova"},
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_update_address_cross_org_blocked(self, client, auth_headers, property_repo):
        """Property in another org → caller is not a member → require_org_member 403s."""
        other_prop = _make_property(address="Cross")
        other_prop.organization_id = UUID(OTHER_ORGANIZATION_ID)
        await property_repo.save(other_prop)

        response = await client.patch(
            f"/api/v1/admin/properties/{other_prop.id}/address?organization_id={OTHER_ORGANIZATION_ID}",
            json={"address": "Rua Nova"},
            headers=auth_headers,
        )
        assert response.status_code in (403, 404)

    async def test_update_address_unauthenticated_returns_401(self, client, auth_headers):
        property_id = await self._create(client, auth_headers)
        response = await client.patch(
            f"/api/v1/admin/properties/{property_id}/address?organization_id={TEST_ORGANIZATION_ID}",
            json={"address": "Rua Nova"},
        )
        assert response.status_code == 401

    async def test_update_address_on_active_property_preserves_status(
        self, client, auth_headers, property_repo
    ):
        prop = _make_property(status=PropertyStatus.ACTIVE, address="Old Active")
        await property_repo.save(prop)

        response = await client.patch(
            f"/api/v1/admin/properties/{prop.id}/address?organization_id={TEST_ORGANIZATION_ID}",
            json={"address": "Rua Nova"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "active"
        assert data["address"] == "Rua Nova"


class TestListActiveProperties:
    async def test_list_active_properties(self, client, property_repo):
        active = _make_property(status=PropertyStatus.ACTIVE, address="Active 1")
        draft = _make_property(status=PropertyStatus.DRAFT, address="Draft 1")
        sold = _make_property(status=PropertyStatus.SOLD, address="Sold 1")
        await property_repo.save(active)
        await property_repo.save(draft)
        await property_repo.save(sold)

        response = await client.get("/api/v1/admin/properties/active")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["address"] == "Active 1"
        assert data[0]["status"] == "active"
        assert "owners" not in data[0]

    async def test_list_active_properties_empty(self, client):
        response = await client.get("/api/v1/admin/properties/active")
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_active_properties_no_auth_required(self, client, property_repo):
        active = _make_property(status=PropertyStatus.ACTIVE, address="Public 1")
        await property_repo.save(active)

        # No auth headers — should still succeed
        response = await client.get("/api/v1/admin/properties/active")
        assert response.status_code == 200
        assert len(response.json()) == 1
