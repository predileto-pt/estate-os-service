from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from contract_intelligence.adapters.database.repositories import (
    SqlAlchemyGeneratedContractRepository,
    SqlAlchemySourceDocumentRepository,
    SqlAlchemySourceSectionRepository,
    SqlAlchemyTemplateRepository,
)
from contract_intelligence.application.ports.unit_of_work import ContractUnitOfWork


class SqlAlchemyContractUnitOfWork(ContractUnitOfWork):
    """SQLAlchemy-backed Unit of Work.

    Each ``async with`` block opens a fresh session, wires the four
    repositories to it, and guarantees rollback on unhandled exceptions.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self):
        self._session = self._session_factory()
        self.source_documents = SqlAlchemySourceDocumentRepository(self._session)
        self.source_sections = SqlAlchemySourceSectionRepository(self._session)
        self.templates = SqlAlchemyTemplateRepository(self._session)
        self.generated_contracts = SqlAlchemyGeneratedContractRepository(self._session)
        return self

    async def commit(self) -> None:
        assert self._session is not None  # noqa: S101
        await self._session.commit()

    async def rollback(self) -> None:
        assert self._session is not None  # noqa: S101
        await self._session.rollback()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        assert self._session is not None  # noqa: S101
        if exc_type:
            await self.rollback()
        await self._session.close()
        self._session = None
