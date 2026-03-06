from uuid import UUID

from supabase import AsyncClient

from core_api.application.ports.repositories.company_repository import CompanyRepository
from core_api.domain.models.company import Company
from core_api.domain.models.value_objects import Address


class SupabaseCompanyRepository(CompanyRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def _to_domain(self, row: dict) -> Company:
        return Company(
            id=UUID(row["id"]),
            name=row["name"],
            tax_id_number=row["tax_id_number"],
            address=Address(
                street=row.get("address_street", ""),
                parish=row.get("address_parish"),
                municipality=row.get("address_municipality"),
                district=row.get("address_district"),
                postal_code=row.get("address_postal_code"),
                country=row.get("address_country", "PT"),
            ),
            stripe_customer_id=row.get("stripe_customer_id"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _to_row(self, company: Company) -> dict:
        return {
            "id": str(company.id),
            "name": company.name,
            "tax_id_number": company.tax_id_number,
            "address_street": company.address.street,
            "address_parish": company.address.parish,
            "address_municipality": company.address.municipality,
            "address_district": company.address.district,
            "address_postal_code": company.address.postal_code,
            "address_country": company.address.country,
            "stripe_customer_id": company.stripe_customer_id,
        }

    async def get_by_id(self, company_id: UUID) -> Company | None:
        result = (
            await self._client.table("companies").select("*").eq("id", str(company_id)).execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def save(self, company: Company) -> Company:
        result = await self._client.table("companies").insert(self._to_row(company)).execute()
        return self._to_domain(result.data[0])

    async def update(self, company: Company) -> Company:
        row = self._to_row(company)
        result = (
            await self._client.table("companies")
            .update(row)
            .eq("id", str(company.id))
            .execute()
        )
        return self._to_domain(result.data[0])
