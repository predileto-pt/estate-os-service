"""create booking management tables

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2026-03-28 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "j6k7l8m9n0o1"
down_revision: Union[str, Sequence[str], None] = "i5j6k7l8m9n0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # booking_applicants
    op.create_table(
        "booking_applicants",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("external_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("supabase_user_id", sa.Text(), nullable=True),
        sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(10), server_default="LOW", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("external_id", name="uq_booking_applicants_external_id"),
    )

    # booking_slots
    op.create_table(
        "booking_slots",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("property_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("agent_user_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), server_default="available", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("end_time > start_time", name="ck_booking_slots_valid_time_range"),
        sa.CheckConstraint(
            "status IN ('available', 'booked', 'cancelled')",
            name="ck_booking_slots_status",
        ),
    )
    op.create_index("idx_booking_slots_property_status", "booking_slots", ["property_id", "status"])
    op.create_index("idx_booking_slots_agent", "booking_slots", ["agent_user_id"])
    op.create_index("idx_booking_slots_org", "booking_slots", ["organization_id"])
    op.create_index("idx_booking_slots_start_time", "booking_slots", ["start_time"])

    # updated_at trigger for booking_slots
    op.execute("""
        CREATE TRIGGER update_booking_slots_updated_at
            BEFORE UPDATE ON booking_slots
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)

    # booking_bookings
    op.create_table(
        "booking_bookings",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("slot_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("applicant_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("property_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("organization_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("status", sa.String(30), server_default="confirmed", nullable=False),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["slot_id"], ["booking_slots.id"]),
        sa.ForeignKeyConstraint(["applicant_id"], ["booking_applicants.id"]),
        sa.UniqueConstraint("slot_id", name="uq_booking_bookings_slot_id"),
        sa.CheckConstraint(
            "status IN ('confirmed', 'cancelled_by_applicant', 'cancelled_by_agent')",
            name="ck_booking_bookings_status",
        ),
    )
    op.create_index("idx_booking_bookings_applicant", "booking_bookings", ["applicant_id"])
    op.create_index("idx_booking_bookings_property", "booking_bookings", ["property_id"])
    op.create_index("idx_booking_bookings_org", "booking_bookings", ["organization_id"])

    # updated_at trigger for booking_bookings
    op.execute("""
        CREATE TRIGGER update_booking_bookings_updated_at
            BEFORE UPDATE ON booking_bookings
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS update_booking_bookings_updated_at ON booking_bookings")
    op.drop_index("idx_booking_bookings_org", table_name="booking_bookings")
    op.drop_index("idx_booking_bookings_property", table_name="booking_bookings")
    op.drop_index("idx_booking_bookings_applicant", table_name="booking_bookings")
    op.drop_table("booking_bookings")

    op.execute("DROP TRIGGER IF EXISTS update_booking_slots_updated_at ON booking_slots")
    op.drop_index("idx_booking_slots_start_time", table_name="booking_slots")
    op.drop_index("idx_booking_slots_org", table_name="booking_slots")
    op.drop_index("idx_booking_slots_agent", table_name="booking_slots")
    op.drop_index("idx_booking_slots_property_status", table_name="booking_slots")
    op.drop_table("booking_slots")

    op.drop_table("booking_applicants")
