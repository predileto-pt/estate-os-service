from uuid import UUID

from core_api.application.ports.repositories.intake_form_request_repository import (
    IntakeFormRequestRepository,
)


class InMemoryIntakeFormRequestRepository(IntakeFormRequestRepository):
    def __init__(self) -> None:
        self._requests: dict[UUID, dict] = {}

    async def get_by_id(self, request_id: UUID) -> dict | None:
        return self._requests.get(request_id)

    async def update_status(self, request_id: UUID, status: str) -> None:
        if request_id in self._requests:
            self._requests[request_id]["status"] = status

    def add(self, request: dict) -> None:
        """Helper for test setup."""
        self._requests[UUID(request["id"])] = request
