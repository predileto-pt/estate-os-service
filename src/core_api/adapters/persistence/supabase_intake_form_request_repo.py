from uuid import UUID

from supabase import AsyncClient

from core_api.application.ports.repositories.intake_form_request_repository import (
    IntakeFormRequestRepository,
)


class SupabaseIntakeFormRequestRepository(IntakeFormRequestRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def get_by_id(self, request_id: UUID) -> dict | None:
        result = (
            await self._client.table("intake_form_requests")
            .select("*")
            .eq("id", str(request_id))
            .execute()
        )
        if not result.data:
            return None
        return result.data[0]

    async def update_status(self, request_id: UUID, status: str) -> None:
        await (
            self._client.table("intake_form_requests")
            .update({"status": status})
            .eq("id", str(request_id))
            .execute()
        )
