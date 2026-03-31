from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from bookings.adapters.database.models import (
    BookingApplicantModel,
    BookingBookingModel,
    BookingSlotModel,
)
from bookings.application.ports.repositories.applicant_repository import (
    BookingApplicantRepository,
)
from bookings.application.ports.repositories.booking_repository import BookingRepository
from bookings.application.ports.repositories.slot_repository import SlotRepository
from bookings.domain.models.applicant import BookingApplicant, RiskLevel
from bookings.domain.models.booking import Booking, BookingStatus
from bookings.domain.models.slot import Slot, SlotStatus


def _slot_from_model(m: BookingSlotModel) -> Slot:
    return Slot(
        id=str(m.id),
        property_id=str(m.property_id),
        agent_user_id=str(m.agent_user_id),
        organization_id=str(m.organization_id),
        start_time=m.start_time,
        end_time=m.end_time,
        status=SlotStatus(m.status),
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _booking_from_model(m: BookingBookingModel) -> Booking:
    return Booking(
        id=str(m.id),
        slot_id=str(m.slot_id),
        applicant_id=str(m.applicant_id),
        property_id=str(m.property_id),
        organization_id=str(m.organization_id),
        status=BookingStatus(m.status),
        notes=m.notes,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def _applicant_from_model(m: BookingApplicantModel) -> BookingApplicant:
    return BookingApplicant(
        id=str(m.id),
        external_id=str(m.external_id),
        supabase_user_id=m.supabase_user_id,
        organization_id=str(m.organization_id),
        name=m.name,
        email=m.email,
        risk_level=RiskLevel(m.risk_level),
        created_at=m.created_at,
    )


class SqlAlchemySlotRepository(SlotRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, slot: Slot) -> Slot:
        model = BookingSlotModel(
            id=slot.id,
            property_id=slot.property_id,
            agent_user_id=slot.agent_user_id,
            organization_id=slot.organization_id,
            start_time=slot.start_time,
            end_time=slot.end_time,
            status=slot.status.value,
        )
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _slot_from_model(model)

    async def find(self, slot_id: str) -> Slot | None:
        result = await self.session.execute(
            select(BookingSlotModel).where(BookingSlotModel.id == slot_id)
        )
        model = result.scalar_one_or_none()
        return _slot_from_model(model) if model else None

    async def mark_booked(self, slot_id: str) -> bool:
        """Optimistic locking: only marks booked if currently available."""
        result = await self.session.execute(
            update(BookingSlotModel)
            .where(BookingSlotModel.id == slot_id, BookingSlotModel.status == "available")
            .values(status="booked", updated_at=text("now()"))
        )
        await self.session.flush()
        return result.rowcount > 0

    async def mark_available(self, slot_id: str) -> None:
        await self.session.execute(
            update(BookingSlotModel)
            .where(BookingSlotModel.id == slot_id)
            .values(status="available", updated_at=text("now()"))
        )
        await self.session.flush()

    async def cancel(self, slot_id: str) -> None:
        await self.session.execute(
            update(BookingSlotModel)
            .where(BookingSlotModel.id == slot_id)
            .values(status="cancelled", updated_at=text("now()"))
        )
        await self.session.flush()

    async def list_available_by_property(
        self, property_id: str, from_time: datetime, limit: int, offset: int
    ) -> tuple[list[Slot], int]:
        base = select(BookingSlotModel).where(
            BookingSlotModel.property_id == property_id,
            BookingSlotModel.status == "available",
            BookingSlotModel.start_time >= from_time,
        )
        count_result = await self.session.execute(select(func.count()).select_from(base.subquery()))
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(BookingSlotModel.start_time).limit(limit).offset(offset)
        )
        return [_slot_from_model(m) for m in result.scalars().all()], total

    async def list_by_agent(
        self, agent_user_id: str, organization_id: str, limit: int, offset: int
    ) -> tuple[list[Slot], int]:
        base = select(BookingSlotModel).where(
            BookingSlotModel.agent_user_id == agent_user_id,
            BookingSlotModel.organization_id == organization_id,
        )
        count_result = await self.session.execute(select(func.count()).select_from(base.subquery()))
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(BookingSlotModel.start_time.desc()).limit(limit).offset(offset)
        )
        return [_slot_from_model(m) for m in result.scalars().all()], total

    async def list_by_property(
        self, property_id: str, organization_id: str, limit: int, offset: int
    ) -> tuple[list[Slot], int]:
        base = select(BookingSlotModel).where(
            BookingSlotModel.property_id == property_id,
            BookingSlotModel.organization_id == organization_id,
        )
        count_result = await self.session.execute(select(func.count()).select_from(base.subquery()))
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(BookingSlotModel.start_time.desc()).limit(limit).offset(offset)
        )
        return [_slot_from_model(m) for m in result.scalars().all()], total


class SqlAlchemyBookingRepository(BookingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, booking: Booking) -> Booking:
        model = BookingBookingModel(
            id=booking.id,
            slot_id=booking.slot_id,
            applicant_id=booking.applicant_id,
            property_id=booking.property_id,
            organization_id=booking.organization_id,
            status=booking.status.value,
            notes=booking.notes,
        )
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _booking_from_model(model)

    async def find(self, booking_id: str) -> Booking | None:
        result = await self.session.execute(
            select(BookingBookingModel).where(BookingBookingModel.id == booking_id)
        )
        model = result.scalar_one_or_none()
        return _booking_from_model(model) if model else None

    async def find_by_slot_id(self, slot_id: str) -> Booking | None:
        result = await self.session.execute(
            select(BookingBookingModel).where(BookingBookingModel.slot_id == slot_id)
        )
        model = result.scalar_one_or_none()
        return _booking_from_model(model) if model else None

    async def update_status(self, booking_id: str, status: BookingStatus) -> None:
        await self.session.execute(
            update(BookingBookingModel)
            .where(BookingBookingModel.id == booking_id)
            .values(status=status.value, updated_at=text("now()"))
        )
        await self.session.flush()

    async def list_by_applicant(
        self, applicant_id: str, limit: int, offset: int
    ) -> tuple[list[Booking], int]:
        base = select(BookingBookingModel).where(BookingBookingModel.applicant_id == applicant_id)
        count_result = await self.session.execute(select(func.count()).select_from(base.subquery()))
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(BookingBookingModel.created_at.desc()).limit(limit).offset(offset)
        )
        return [_booking_from_model(m) for m in result.scalars().all()], total

    async def list_by_organization(
        self, organization_id: str, limit: int, offset: int
    ) -> tuple[list[Booking], int]:
        base = select(BookingBookingModel).where(
            BookingBookingModel.organization_id == organization_id
        )
        count_result = await self.session.execute(select(func.count()).select_from(base.subquery()))
        total = count_result.scalar() or 0

        result = await self.session.execute(
            base.order_by(BookingBookingModel.created_at.desc()).limit(limit).offset(offset)
        )
        return [_booking_from_model(m) for m in result.scalars().all()], total


class SqlAlchemyBookingApplicantRepository(BookingApplicantRepository):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, applicant: BookingApplicant) -> BookingApplicant:
        model = BookingApplicantModel(
            id=applicant.id,
            external_id=applicant.external_id,
            supabase_user_id=applicant.supabase_user_id,
            organization_id=applicant.organization_id,
            name=applicant.name,
            email=applicant.email,
            risk_level=applicant.risk_level.value,
        )
        self.session.add(model)
        await self.session.flush()
        await self.session.refresh(model)
        return _applicant_from_model(model)

    async def find_by_external_id(self, external_id: str) -> BookingApplicant | None:
        result = await self.session.execute(
            select(BookingApplicantModel).where(BookingApplicantModel.external_id == external_id)
        )
        model = result.scalar_one_or_none()
        return _applicant_from_model(model) if model else None

    async def find_by_supabase_user_id(self, supabase_user_id: str) -> BookingApplicant | None:
        result = await self.session.execute(
            select(BookingApplicantModel).where(
                BookingApplicantModel.supabase_user_id == supabase_user_id
            )
        )
        model = result.scalar_one_or_none()
        return _applicant_from_model(model) if model else None

    async def link_supabase_account(self, applicant_id: str, supabase_user_id: str) -> None:
        await self.session.execute(
            update(BookingApplicantModel)
            .where(BookingApplicantModel.id == applicant_id)
            .values(supabase_user_id=supabase_user_id)
        )
        await self.session.flush()
