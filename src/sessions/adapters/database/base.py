"""Portal-DB SQLAlchemy declarative base.

Distinct from `shared.database.models.Base` so the admin-DB MetaData and
portal-DB MetaData never share state. The alembic-portal autogenerate
target points at `Base.metadata` here.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
