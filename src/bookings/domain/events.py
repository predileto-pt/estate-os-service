from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicantScreenedEvent:
    applicant_id: str
    organization_id: str
    form_request_id: str
    name: str
    email: str
    risk_level: str
