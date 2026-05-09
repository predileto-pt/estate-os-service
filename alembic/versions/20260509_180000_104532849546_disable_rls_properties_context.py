"""disable RLS on the properties-context tables

Revision ID: 104532849546
Revises: a6ec66e613a1
Create Date: 2026-05-09 18:00:00.000000

Symptom: enrichment workflow reports `pois_discovered=10` in
`background_jobs` but `property_pois` count stays at 0 and
`properties.aggregate_version` doesn't bump. Same Supabase service-role
client successfully writes to `background_jobs`. PostgREST + RLS is
silently filtering UPDATE/INSERT rows on `properties` and
`property_pois` (returning 0 rows affected with no error), almost
certainly because the original policy

    CREATE POLICY "Users can manage their own properties"
        ON properties FOR ALL
        USING (user_id = auth.uid())
        WITH CHECK (user_id = auth.uid());

was left in place after the `user_id → organization_id` rename
migration (`20260317_181500_a1b2c3d4e5f6`), interacting badly with
the service-role policy.

Resolution per the operator's call: don't rely on Supabase RLS for
authz on the properties-context tables. The app already enforces
org membership via `require_org_member` on every admin route and
via container-level wiring on workers (which only run with the
service-role key anyway). Removing RLS is the cleanest unblock.

If RLS is reintroduced later, the rule the operator wants is:
"every member of an organization can read/write rows belonging to
that organization." That'd look like:

    CREATE POLICY membership_read_write
        ON <table> FOR ALL
        USING (organization_id IN (
            SELECT organization_id FROM memberships
            WHERE user_id = auth.uid()
        ))
        WITH CHECK (organization_id IN (
            SELECT organization_id FROM memberships
            WHERE user_id = auth.uid()
        ));

Out of scope here; tracked as a follow-up.

This migration disables RLS on the seven properties-context tables.
Other contexts (organizations, identity, billing, screening, bookings,
contract_intelligence) still have their RLS in place — touch only
what we know is broken.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "104532849546"
down_revision: Union[str, Sequence[str], None] = "a6ec66e613a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES = (
    "properties",
    "property_owners",
    "property_images",
    "property_prices",
    "property_pois",
    "extraction_jobs",
    "document_contents",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
        # Drop ALL policies on the table — they're irrelevant once RLS
        # is off, and leaving stale policies referencing a renamed
        # `user_id` column is what got us here in the first place.
        op.execute(f"""
            DO $$
            DECLARE
                pol record;
            BEGIN
                FOR pol IN
                    SELECT policyname FROM pg_policies WHERE tablename = '{table}'
                LOOP
                    EXECUTE format('DROP POLICY IF EXISTS %I ON {table};', pol.policyname);
                END LOOP;
            END $$;
        """)


def downgrade() -> None:
    # Best-effort restore: re-enable RLS and recreate the
    # service-role-only policy. The historical "Users can manage..."
    # policies that referenced the renamed `user_id` column are NOT
    # restored — they were broken at HEAD anyway.
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"""
            CREATE POLICY {table}_service_role
            ON {table} FOR ALL USING (auth.role() = 'service_role');
        """)
