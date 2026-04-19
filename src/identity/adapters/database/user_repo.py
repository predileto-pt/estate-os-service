from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from identity.adapters.database.models import UserModel
from identity.application.ports.repositories.user_repository import UserRepository
from identity.domain.models.user import User
from identity.domain.value_objects import PhoneNumber


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_domain(m: UserModel) -> User:
        phone = None
        if m.phone_country_code and m.phone_number:
            phone = PhoneNumber(country_code=m.phone_country_code, number=m.phone_number)
        return User(
            id=UUID(m.id),
            supabase_user_id=m.supabase_user_id,
            email=m.email,
            name=m.name,
            phone=phone,
            google_metadata=m.google_metadata,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _to_model(u: User) -> UserModel:
        return UserModel(
            id=str(u.id),
            supabase_user_id=u.supabase_user_id,
            email=u.email,
            name=u.name,
            phone_country_code=u.phone.country_code if u.phone else None,
            phone_number=u.phone.number if u.phone else None,
            google_metadata=u.google_metadata,
        )

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(select(UserModel).where(UserModel.id == str(user_id)))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_supabase_id(self, supabase_user_id: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.supabase_user_id == supabase_user_id)
        )
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(UserModel).where(UserModel.email == email))
        row = result.scalar_one_or_none()
        return self._to_domain(row) if row else None

    async def save(self, user: User) -> User:
        model = self._to_model(user)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)

    async def update(self, user: User) -> User:
        result = await self._session.execute(select(UserModel).where(UserModel.id == str(user.id)))
        model = result.scalar_one()
        model.supabase_user_id = user.supabase_user_id
        model.email = user.email
        model.name = user.name
        model.phone_country_code = user.phone.country_code if user.phone else None
        model.phone_number = user.phone.number if user.phone else None
        model.google_metadata = user.google_metadata
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_domain(model)
