from uuid import UUID

from supabase import AsyncClient

from organizations.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from organizations.domain.models.organization import Organization
from organizations.domain.value_objects import PhoneNumber


class SupabaseOrganizationRepository(OrganizationRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def _to_domain(self, row: dict) -> Organization:
        phone = None
        if row.get("phone_country_code") and row.get("phone_number"):
            phone = PhoneNumber(
                country_code=row["phone_country_code"],
                number=row["phone_number"],
            )
        return Organization(
            id=UUID(row["id"]),
            created_by=UUID(row["created_by"]),
            name=row["name"],
            nif=row["nif"],
            address=row["address"],
            email=row.get("email"),
            phone=phone,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _to_row(self, organization: Organization) -> dict:
        return {
            "id": str(organization.id),
            "created_by": str(organization.created_by),
            "name": organization.name,
            "nif": organization.nif,
            "address": organization.address,
            "email": organization.email,
            "phone_country_code": organization.phone.country_code if organization.phone else None,
            "phone_number": organization.phone.number if organization.phone else None,
        }

    async def get_by_id(self, organization_id: UUID) -> Organization | None:
        result = (
            await self._client.table("organizations")
            .select("*")
            .eq("id", str(organization_id))
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def save(self, organization: Organization) -> Organization:
        result = (
            await self._client.table("organizations").insert(self._to_row(organization)).execute()
        )
        return self._to_domain(result.data[0])

    async def update(self, organization: Organization) -> Organization:
        row = self._to_row(organization)
        result = (
            await self._client.table("organizations")
            .update(row)
            .eq("id", str(organization.id))
            .execute()
        )
        return self._to_domain(result.data[0])
