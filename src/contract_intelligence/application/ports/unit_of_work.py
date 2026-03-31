from contract_intelligence.application.ports.repositories import (
    GeneratedContractRepository,
    SourceDocumentRepository,
    SourceSectionRepository,
    TemplateRepository,
)
from shared.ports.unit_of_work import UnitOfWork


class ContractUnitOfWork(UnitOfWork):
    """Unit of Work for the contract_intelligence bounded context.

    Exposes the four repositories as attributes; implementations must
    initialise them in ``__aenter__``.
    """

    source_documents: SourceDocumentRepository
    source_sections: SourceSectionRepository
    templates: TemplateRepository
    generated_contracts: GeneratedContractRepository
