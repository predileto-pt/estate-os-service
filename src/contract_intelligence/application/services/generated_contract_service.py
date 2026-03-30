from __future__ import annotations

import uuid

from contract_intelligence.application.dtos.generated_contracts import (
    CreateGeneratedContractFromCRMRequest,
    GeneratedContractRead,
    RenderGeneratedContractResponse,
)
from contract_intelligence.application.ports.repositories import GeneratedContractRepository


class GeneratedContractService:
    def __init__(self, repo: GeneratedContractRepository) -> None:
        self._repo = repo

    async def create_from_crm(
        self, payload: CreateGeneratedContractFromCRMRequest
    ) -> GeneratedContractRead:
        raise NotImplementedError

    async def get_generated_contract(self, contract_id: uuid.UUID) -> GeneratedContractRead:
        raise NotImplementedError

    async def render_generated_contract(
        self, contract_id: uuid.UUID
    ) -> RenderGeneratedContractResponse:
        raise NotImplementedError
