from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

from core_api.application.ports.event_bus import EventBus
from core_api.application.ports.repositories.applicant_repository import ApplicantRepository
from core_api.application.ports.repositories.intake_form_request_repository import (
    IntakeFormRequestRepository,
)
from core_api.domain.events import ApplicantScreened
from core_api.domain.models.applicant import Applicant, ApplicantStatus, IncomeRecord

log = structlog.get_logger()


class ProcessScreeningResult:
    def __init__(
        self,
        applicant_repo: ApplicantRepository,
        intake_form_request_repo: IntakeFormRequestRepository,
        event_bus: EventBus,
    ) -> None:
        self.applicant_repo = applicant_repo
        self.intake_form_request_repo = intake_form_request_repo
        self.event_bus = event_bus

    async def execute(self, event_data: dict) -> Applicant:
        form_request_id = UUID(event_data["form_request_id"])
        screening_applicant_id = UUID(event_data["applicant_id"])
        owner_id = UUID(event_data["owner_id"])

        # Look up the intake form request for property + agency info
        form_request = await self.intake_form_request_repo.get_by_id(form_request_id)
        if not form_request:
            raise ValueError(f"IntakeFormRequest {form_request_id} not found")

        now = datetime.now(timezone.utc)

        # Extract screening data
        screening = event_data.get("screening", {})

        # Build income records from screening data if available
        income_records: list[IncomeRecord] = []
        for rec in event_data.get("income_records", []):
            income_records.append(
                IncomeRecord(month=rec["month"], amount=rec["amount"], source=rec["source"])
            )

        # Parse date of birth
        dob_str = event_data.get("date_of_birth")
        from datetime import date

        dob = date.fromisoformat(dob_str) if dob_str else None

        applicant = Applicant(
            id=uuid4(),
            property_id=form_request["property_id"],
            property_title=form_request.get("property_title") or form_request["property_id"],
            visitor_name=event_data["name"],
            visitor_email=event_data["email"],
            agency_id=owner_id,
            status=ApplicantStatus.PENDING,
            created_at=now,
            updated_at=now,
            visitor_phone=form_request.get("applicant_phone"),
            visitor_nif=event_data.get("nif"),
            visitor_date_of_birth=dob,
            property_price=form_request.get("property_price") or event_data.get("monthly_rent"),
            property_address=form_request.get("property_address"),
            has_id_document=event_data.get("has_id_document", False),
            has_proof_of_income=event_data.get("has_proof_of_income", False),
            justification=screening.get("justification"),
            income_records=income_records,
            form_request_id=form_request_id,
            screening_applicant_id=screening_applicant_id,
        )

        applicant = await self.applicant_repo.save(applicant)

        # Mark intake form request as completed
        await self.intake_form_request_repo.update_status(form_request_id, "completed")

        # Publish domain event
        risk_level = screening.get("risk_level", "")
        await self.event_bus.publish(
            ApplicantScreened(
                applicant_id=applicant.id,
                agency_id=applicant.agency_id,
                risk_level=risk_level,
            )
        )

        log.info(
            "screening_result_processed",
            applicant_id=str(applicant.id),
            form_request_id=str(form_request_id),
            risk_level=risk_level,
        )
        return applicant
