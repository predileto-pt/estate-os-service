from shared.database.models import Base
import customer_management.adapters.database.models  # noqa: F401 — register models
import property_management.adapters.database.models  # noqa: F401 — register models


EXPECTED_TABLES = {
    "organizations",
    "users",
    "subscriptions",
    "notifications",
    "memberships",
    "invitations",
    "properties",
    "property_owners",
    "extraction_jobs",
    "document_contents",
}


def test_all_tables_registered():
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_organizations_columns():
    cols = {c.name for c in Base.metadata.tables["organizations"].columns}
    assert cols == {
        "id",
        "created_by",
        "name",
        "nif",
        "address",
        "created_at",
        "updated_at",
    }


def test_users_columns():
    cols = {c.name for c in Base.metadata.tables["users"].columns}
    assert cols == {
        "id",
        "supabase_user_id",
        "email",
        "name",
        "phone_country_code",
        "phone_number",
        "organization_id",
        "google_metadata",
        "created_at",
        "updated_at",
    }


def test_subscriptions_columns():
    cols = {c.name for c in Base.metadata.tables["subscriptions"].columns}
    assert cols == {
        "id",
        "organization_id",
        "plan",
        "type",
        "status",
        "stripe_subscription_id",
        "stripe_price_id",
        "current_period_start",
        "current_period_end",
        "created_at",
        "updated_at",
    }


def test_notifications_columns():
    cols = {c.name for c in Base.metadata.tables["notifications"].columns}
    assert cols == {
        "id",
        "user_id",
        "title",
        "message",
        "status",
        "channel",
        "created_at",
        "read_at",
    }


def test_memberships_columns():
    cols = {c.name for c in Base.metadata.tables["memberships"].columns}
    assert cols == {
        "id",
        "user_id",
        "organization_id",
        "role",
        "created_at",
        "updated_at",
    }


def test_invitations_columns():
    cols = {c.name for c in Base.metadata.tables["invitations"].columns}
    assert cols == {
        "id",
        "organization_id",
        "email",
        "role",
        "invited_by",
        "token",
        "status",
        "expires_at",
        "created_at",
    }


def test_notifications_user_status_index():
    table = Base.metadata.tables["notifications"]
    index_names = {idx.name for idx in table.indexes}
    assert "idx_notifications_user_status" in index_names


def test_memberships_organization_index():
    table = Base.metadata.tables["memberships"]
    index_names = {idx.name for idx in table.indexes}
    assert "idx_memberships_organization_id" in index_names
