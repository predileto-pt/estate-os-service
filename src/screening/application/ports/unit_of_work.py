from screening.application.ports.repositories.applicant_repository import ApplicantRepository
from screening.application.ports.repositories.document_repository import DocumentRepository
from screening.application.ports.repositories.event_repository import EventRepository
from screening.application.ports.repositories.extracted_data_repository import (
    ExtractedDataRepository,
)
from screening.application.ports.repositories.intake_form_request_repository import (
    IntakeFormRequestRepository,
)
from screening.application.ports.repositories.screening_report_repository import (
    ScreeningReportRepository,
)
from screening.application.ports.repositories.submission_repository import SubmissionRepository
from shared.ports.unit_of_work import UnitOfWork


class ScreeningUnitOfWork(UnitOfWork):
    """Unit of Work for the screening bounded context.

    Exposes the seven repositories as attributes; implementations must
    initialise them in ``__aenter__``.
    """

    applicants: ApplicantRepository
    documents: DocumentRepository
    extracted_data: ExtractedDataRepository
    screening_reports: ScreeningReportRepository
    events: EventRepository
    intake_form_requests: IntakeFormRequestRepository
    submissions: SubmissionRepository
