from uuid import UUID

from supabase import AsyncClient

from customer_management.application.ports.repositories.company_repository import CompanyRepository
from customer_management.domain.models.company import Company


class SupabaseCompanyRepository(CompanyRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def _to_domain(self, row: dict) -> Company:
        return Company(
            id=UUID(row["id"]),
            user_id=UUID(row["user_id"]),
            name=row["name"],
            nif=row["nif"],
            address=row["address"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _to_row(self, company: Company) -> dict:
        return {
            "id": str(company.id),
            "user_id": str(company.user_id),
            "name": company.name,
            "nif": company.nif,
            "address": company.address,
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
            await self._client.table("companies").update(row).eq("id", str(company.id)).execute()
        )
        return self._to_domain(result.data[0])
