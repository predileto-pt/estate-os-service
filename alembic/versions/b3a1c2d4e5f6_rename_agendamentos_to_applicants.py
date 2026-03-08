"""rename agendamentos to applicants

Revision ID: b3a1c2d4e5f6
Revises: 9f8f4ad7c7ea
Create Date: 2026-03-08

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3a1c2d4e5f6"
down_revision: Union[str, None] = "9f8f4ad7c7ea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Rename enum type -----------------------------------------------------
    op.execute("ALTER TYPE agendamento_status RENAME TO applicant_status")

    # -- Drop RLS policies (reference old table name) -------------------------
    op.execute('DROP POLICY IF EXISTS "Anyone can insert visit requests" ON agendamentos')
    op.execute('DROP POLICY IF EXISTS "Users can update own visit requests" ON agendamentos')
    op.execute('DROP POLICY IF EXISTS "Users can view own visit requests" ON agendamentos')

    # -- Drop trigger (references old table name) -----------------------------
    op.execute("DROP TRIGGER IF EXISTS trg_agendamentos_updated_at ON agendamentos")

    # -- Rename table ---------------------------------------------------------
    op.rename_table("agendamentos", "applicants")

    # -- Recreate trigger with new name ---------------------------------------
    op.execute("""
        CREATE TRIGGER trg_applicants_updated_at
            BEFORE UPDATE ON applicants
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # -- Recreate RLS policies on new table name ------------------------------
    op.execute("ALTER TABLE applicants ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY "Users can view own applicants"
            ON applicants FOR SELECT USING (auth.uid() = agency_id);
    """)
    op.execute("""
        CREATE POLICY "Users can update own applicants"
            ON applicants FOR UPDATE USING (auth.uid() = agency_id);
    """)
    op.execute("""
        CREATE POLICY "Anyone can insert applicants"
            ON applicants FOR INSERT WITH CHECK (true);
    """)


def downgrade() -> None:
    # -- Drop new RLS policies ------------------------------------------------
    op.execute('DROP POLICY IF EXISTS "Anyone can insert applicants" ON applicants')
    op.execute('DROP POLICY IF EXISTS "Users can update own applicants" ON applicants')
    op.execute('DROP POLICY IF EXISTS "Users can view own applicants" ON applicants')

    # -- Drop new trigger -----------------------------------------------------
    op.execute("DROP TRIGGER IF EXISTS trg_applicants_updated_at ON applicants")

    # -- Rename table back ----------------------------------------------------
    op.rename_table("applicants", "agendamentos")

    # -- Recreate old trigger -------------------------------------------------
    op.execute("""
        CREATE TRIGGER trg_agendamentos_updated_at
            BEFORE UPDATE ON agendamentos
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # -- Recreate old RLS policies --------------------------------------------
    op.execute("ALTER TABLE agendamentos ENABLE ROW LEVEL SECURITY;")
    op.execute("""
        CREATE POLICY "Users can view own visit requests"
            ON agendamentos FOR SELECT USING (auth.uid() = agency_id);
    """)
    op.execute("""
        CREATE POLICY "Users can update own visit requests"
            ON agendamentos FOR UPDATE USING (auth.uid() = agency_id);
    """)
    op.execute("""
        CREATE POLICY "Anyone can insert visit requests"
            ON agendamentos FOR INSERT WITH CHECK (true);
    """)

    # -- Rename enum type back ------------------------------------------------
    op.execute("ALTER TYPE applicant_status RENAME TO agendamento_status")
