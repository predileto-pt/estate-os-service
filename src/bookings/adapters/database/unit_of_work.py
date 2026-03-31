from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bookings.adapters.database.repositories import (
    SqlAlchemyBookingApplicantRepository,
    SqlAlchemyBookingRepository,
    SqlAlchemySlotRepository,
)
from bookings.application.ports.unit_of_work import BookingUnitOfWork


class SqlAlchemyBookingUnitOfWork(BookingUnitOfWork):
    """SQLAlchemy-backed Unit of Work for the bookings bounded context.

    Each ``async with`` block opens a fresh session, wires all repositories
    to it, and guarantees rollback on unhandled exceptions.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self):
        self._session = self._session_factory()
        self.slots = SqlAlchemySlotRepository(self._session)
        self.bookings = SqlAlchemyBookingRepository(self._session)
        self.applicants = SqlAlchemyBookingApplicantRepository(self._session)
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
