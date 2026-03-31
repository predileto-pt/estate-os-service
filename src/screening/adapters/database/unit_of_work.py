from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from screening.adapters.database.repositories import (
    SqlAlchemyApplicantRepository,
    SqlAlchemyDocumentRepository,
    SqlAlchemyEventRepository,
    SqlAlchemyExtractedDataRepository,
    SqlAlchemyIntakeFormRequestRepository,
    SqlAlchemyScreeningReportRepository,
    SqlAlchemySubmissionRepository,
)
from screening.application.ports.unit_of_work import ScreeningUnitOfWork


class SqlAlchemyScreeningUnitOfWork(ScreeningUnitOfWork):
    """SQLAlchemy-backed Unit of Work for the screening bounded context.

    Each ``async with`` block opens a fresh session, wires all repositories
    to it, and guarantees rollback on unhandled exceptions.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        public_key: RSAPublicKey,
        private_key: RSAPrivateKey,
        hmac_key: bytes,
    ) -> None:
        self._session_factory = session_factory
        self._public_key = public_key
        self._private_key = private_key
        self._hmac_key = hmac_key
        self._session: AsyncSession | None = None

    async def __aenter__(self):
        self._session = self._session_factory()
        self.applicants = SqlAlchemyApplicantRepository(
            self._session, self._public_key, self._private_key, self._hmac_key
        )
        self.documents = SqlAlchemyDocumentRepository(self._session)
        self.extracted_data = SqlAlchemyExtractedDataRepository(self._session)
        self.screening_reports = SqlAlchemyScreeningReportRepository(self._session)
        self.events = SqlAlchemyEventRepository(self._session)
        self.intake_form_requests = SqlAlchemyIntakeFormRequestRepository(self._session)
        self.submissions = SqlAlchemySubmissionRepository(self._session)
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
