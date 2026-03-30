class DomainError(Exception):
    pass


class SourceDocumentNotFoundError(DomainError):
    pass


class DuplicateDocumentHashError(DomainError):
    pass


class SourceSectionNotFoundError(DomainError):
    pass


class FieldEvidenceNotFoundError(DomainError):
    pass


class TemplateNotFoundError(DomainError):
    pass


class TemplateVersionNotFoundError(DomainError):
    pass


class TemplateSectionNotFoundError(DomainError):
    pass


class TemplateVersionAlreadyPublishedError(DomainError):
    pass


class GeneratedContractNotFoundError(DomainError):
    pass


class InvalidStatusTransitionError(DomainError):
    pass
