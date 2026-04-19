"""SQLAlchemy User model.

The schema still has a nullable `organization_id` FK and a `portal_users`
table at this point in the spec's commit sequence — those are dropped in
the identity-split Alembic migration (a later commit). This model maps the
post-drop shape: no `organization_id`. Tests against the pre-migration DB
would fail to UPDATE/SELECT — tests use either a fresh DB (SQLAlchemy
`create_all`) or run the migration first.
"""

from datetime import datetime

from sqlalchemy import DateTime, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.database.models import Base


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )
    supabase_user_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_country_code: Mapped[str | None] = mapped_column(Text)
    phone_number: Mapped[str | None] = mapped_column(Text)
    google_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("supabase_user_id", name="uq_users_supabase_user_id"),
        UniqueConstraint("email", name="uq_users_email"),
    )
