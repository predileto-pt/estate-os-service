from uuid import uuid4

from core_api.adapters.inmemory.inmemory_applicant_repo import InMemoryApplicantRepository
from core_api.adapters.inmemory.inmemory_event_bus import InMemoryEventBus
from core_api.adapters.inmemory.inmemory_intake_form_request_repo import (
    InMemoryIntakeFormRequestRepository,
)
from core_api.application.use_cases.process_screening_result import ProcessScreeningResult
from core_api.domain.events import ApplicantScreened


async def test_process_screening_result_creates_applicant():
    applicant_repo = InMemoryApplicantRepository()
    intake_repo = InMemoryIntakeFormRequestRepository()
    event_bus = InMemoryEventBus()

    form_request_id = str(uuid4())
    agency_id = str(uuid4())

    intake_repo.add({
        "id": form_request_id,
        "agency_id": agency_id,
        "applicant_name": "João Silva",
        "applicant_email": "joao@example.com",
        "applicant_phone": "+351912345678",
        "property_id": "prop-123",
        "property_title": "Apartamento T2",
        "property_price": 850.0,
        "property_address": "Rua Augusta, Lisboa",
        "status": "pending",
    })

    use_case = ProcessScreeningResult(
        applicant_repo=applicant_repo,
        intake_form_request_repo=intake_repo,
        event_bus=event_bus,
    )

    event_data = {
        "event_type": "APPLICANT_SCREENED",
        "applicant_id": str(uuid4()),
        "form_request_id": form_request_id,
        "owner_id": agency_id,
        "name": "João Silva",
        "email": "joao@example.com",
        "date_of_birth": "1990-05-15",
        "property_type": "RENTAL",
        "monthly_rent": 850.0,
        "has_id_document": True,
        "has_proof_of_income": True,
        "screening": {
            "risk_level": "LOW",
            "identity_verified": True,
            "income_verified": True,
            "dti_ratio": 0.28,
            "justification": "All checks passed.",
            "average_monthly_income": 3000.0,
        },
        "income_records": [],
    }

    applicant = await use_case.execute(event_data)

    assert applicant.visitor_name == "João Silva"
    assert applicant.visitor_email == "joao@example.com"
    assert applicant.property_id == "prop-123"
    assert applicant.property_title == "Apartamento T2"
    assert applicant.property_price == 850.0
    assert applicant.property_address == "Rua Augusta, Lisboa"
    assert applicant.has_id_document is True
    assert applicant.has_proof_of_income is True
    assert applicant.justification == "All checks passed."
    assert applicant.visitor_phone == "+351912345678"
    assert applicant.status.value == "pending"
    assert applicant.form_request_id is not None

    # Check intake form request marked as completed
    form_request = await intake_repo.get_by_id(applicant.form_request_id)
    assert form_request["status"] == "completed"

    # Check domain event published
    assert len(event_bus.events) == 1
    assert isinstance(event_bus.events[0], ApplicantScreened)
    assert event_bus.events[0].risk_level == "LOW"


async def test_process_screening_result_missing_form_request():
    applicant_repo = InMemoryApplicantRepository()
    intake_repo = InMemoryIntakeFormRequestRepository()
    event_bus = InMemoryEventBus()

    use_case = ProcessScreeningResult(
        applicant_repo=applicant_repo,
        intake_form_request_repo=intake_repo,
        event_bus=event_bus,
    )

    event_data = {
        "event_type": "APPLICANT_SCREENED",
        "applicant_id": str(uuid4()),
        "form_request_id": str(uuid4()),
        "owner_id": str(uuid4()),
        "name": "Test",
        "email": "test@example.com",
        "date_of_birth": "1990-01-01",
        "screening": {"risk_level": "LOW"},
    }

    try:
        await use_case.execute(event_data)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "not found" in str(e)
