from typing import Any

import structlog

from bookings.application.ports.repositories.applicant_repository import (
    BookingApplicantRepository,
)
from bookings.domain.models.applicant import BookingApplicant

logger = structlog.get_logger()


class ApplicantService:
    def __init__(self, applicant_repo: BookingApplicantRepository) -> None:
        self.applicant_repo = applicant_repo

    async def create_from_screening(self, data: dict[str, Any]) -> BookingApplicant:
        applicant_id = str(data.get("applicant_id", ""))

        # Idempotency: check if already exists.
        existing = await self.applicant_repo.find_by_external_id(applicant_id)
        if existing is not None:
            logger.info("applicant_already_exists", external_id=applicant_id)
            return existing

        # Domain validates and rejects HIGH risk.
        applicant = BookingApplicant.from_screening_event(data)
        created = await self.applicant_repo.create(applicant)
        logger.info(
            "applicant_created_from_screening",
            external_id=applicant_id,
            risk_level=data.get("screening", {}).get("risk_level"),
        )
        return created

    async def find_by_external_id(self, external_id: str) -> BookingApplicant | None:
        return await self.applicant_repo.find_by_external_id(external_id)

    async def find_by_supabase_user_id(self, supabase_user_id: str) -> BookingApplicant | None:
        return await self.applicant_repo.find_by_supabase_user_id(supabase_user_id)
