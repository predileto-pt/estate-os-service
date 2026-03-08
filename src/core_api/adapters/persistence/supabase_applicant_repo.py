from datetime import date
from uuid import UUID

from supabase import AsyncClient

from core_api.application.ports.repositories.applicant_repository import ApplicantRepository
from core_api.domain.models.applicant import Applicant, ApplicantStatus, IncomeRecord


class SupabaseApplicantRepository(ApplicantRepository):
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    def _to_domain(self, row: dict) -> Applicant:
        income_records = []
        if row.get("income_records"):
            income_records = [
                IncomeRecord(month=r["month"], amount=r["amount"], source=r["source"])
                for r in row["income_records"]
            ]

        dob = row.get("visitor_date_of_birth")
        if dob and isinstance(dob, str):
            dob = date.fromisoformat(dob)

        return Applicant(
            id=UUID(row["id"]),
            property_id=row["property_id"],
            property_title=row["property_title"],
            visitor_name=row["visitor_name"],
            visitor_email=row["visitor_email"],
            agency_id=UUID(row["agency_id"]),
            status=ApplicantStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            visitor_phone=row.get("visitor_phone"),
            visitor_nif=row.get("visitor_nif"),
            visitor_date_of_birth=dob,
            property_price=row.get("property_price"),
            property_address=row.get("property_address"),
            has_id_document=row.get("has_id_document", False),
            has_proof_of_income=row.get("has_proof_of_income", False),
            justification=row.get("justification"),
            message=row.get("message"),
            income_records=income_records,
            resolved_at=row.get("resolved_at"),
            form_request_id=UUID(row["form_request_id"]) if row.get("form_request_id") else None,
            screening_applicant_id=(
                UUID(row["screening_applicant_id"]) if row.get("screening_applicant_id") else None
            ),
        )

    def _to_row(self, applicant: Applicant) -> dict:
        row: dict = {
            "id": str(applicant.id),
            "property_id": applicant.property_id,
            "property_title": applicant.property_title,
            "visitor_name": applicant.visitor_name,
            "visitor_email": applicant.visitor_email,
            "agency_id": str(applicant.agency_id),
            "status": applicant.status.value,
            "has_id_document": applicant.has_id_document,
            "has_proof_of_income": applicant.has_proof_of_income,
            "visitor_phone": applicant.visitor_phone,
            "visitor_nif": applicant.visitor_nif,
            "visitor_date_of_birth": (
                applicant.visitor_date_of_birth.isoformat()
                if applicant.visitor_date_of_birth
                else None
            ),
            "property_price": applicant.property_price,
            "property_address": applicant.property_address,
            "justification": applicant.justification,
            "message": applicant.message,
            "income_records": (
                [
                    {"month": r.month, "amount": r.amount, "source": r.source}
                    for r in applicant.income_records
                ]
                if applicant.income_records
                else None
            ),
            "form_request_id": (
                str(applicant.form_request_id) if applicant.form_request_id else None
            ),
            "screening_applicant_id": (
                str(applicant.screening_applicant_id) if applicant.screening_applicant_id else None
            ),
        }
        return row

    async def get_by_id(self, applicant_id: UUID) -> Applicant | None:
        result = (
            await self._client.table("applicants").select("*").eq("id", str(applicant_id)).execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def get_by_form_request_id(self, form_request_id: UUID) -> Applicant | None:
        result = (
            await self._client.table("applicants")
            .select("*")
            .eq("form_request_id", str(form_request_id))
            .execute()
        )
        if not result.data:
            return None
        return self._to_domain(result.data[0])

    async def save(self, applicant: Applicant) -> Applicant:
        result = await self._client.table("applicants").insert(self._to_row(applicant)).execute()
        return self._to_domain(result.data[0])

    async def update(self, applicant: Applicant) -> Applicant:
        row = self._to_row(applicant)
        result = (
            await self._client.table("applicants").update(row).eq("id", str(applicant.id)).execute()
        )
        return self._to_domain(result.data[0])
