class DomainError(Exception):
    pass


class ApplicantNotFoundError(DomainError):
    def __init__(self, identifier: str) -> None:
        super().__init__(f"Applicant not found: {identifier}")


class DuplicateApplicantError(DomainError):
    def __init__(self) -> None:
        super().__init__("An applicant with this NIF has already been submitted")


class DocumentLimitExceededError(DomainError):
    def __init__(self, max_documents: int) -> None:
        super().__init__(f"Maximum number of documents exceeded: {max_documents}")


class DocumentNotFoundError(DomainError):
    def __init__(self, identifier: str) -> None:
        super().__init__(f"Document not found: {identifier}")


class ExtractionError(DomainError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"Document extraction failed: {detail}")


class ScreeningError(DomainError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"Screening assessment failed: {detail}")


class IntakeFormRequestNotFoundError(DomainError):
    pass


class SubmissionNotFoundError(DomainError):
    pass
