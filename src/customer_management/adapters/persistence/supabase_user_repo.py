from uuid import UUID

from supabase import AsyncClient

from customer_management.application.ports.repositories.user_repository import UserRepository
from customer_management.domain.models.user import User
from customer_management.domain.models.value_objects import PhoneNumber


class SupabaseUserRepository(UserRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def _to_domain(self, row: dict) -> User:
        phone = None
        if row.get("phone_country_code") and row.get("phone_number"):
            phone = PhoneNumber(country_code=row["phone_country_code"], number=row["phone_number"])
        return User(
            id=UUID(row["id"]),
            supabase_user_id=row["supabase_user_id"],
            email=row["email"],
            name=row["name"],
            phone=phone,
            company_id=UUID(row["company_id"]),
            google_metadata=row.get("google_metadata"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _to_row(self, user: User) -> dict:
        return {
            "id": str(user.id),
            "supabase_user_id": user.supabase_user_id,
            "email": user.email,
            "name": user.name,
            "phone_country_code": user.phone.country_code if user.phone else None,
            "phone_number": user.phone.number if user.phone else None,
            "company_id": str(user.company_id),
            "google_metadata": user.google_metadata,
        }

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._client.table("users").select("*").eq("id", str(user_id)).execute()
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def get_by_supabase_id(self, supabase_user_id: str) -> User | None:
        result = (
            await self._client.table("users")
            .select("*")
            .eq("supabase_user_id", supabase_user_id)
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def get_by_email(self, email: str) -> User | None:
        result = await self._client.table("users").select("*").eq("email", email).execute()
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def save(self, user: User) -> User:
        result = await self._client.table("users").insert(self._to_row(user)).execute()
        return self._to_domain(result.data[0])

    async def update(self, user: User) -> User:
        row = self._to_row(user)
        result = await self._client.table("users").update(row).eq("id", str(user.id)).execute()
        return self._to_domain(result.data[0])
