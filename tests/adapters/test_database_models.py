from shared.database.models import Base
import customer_management.adapters.database.models  # noqa: F401 — register models


EXPECTED_TABLES = {"companies", "users", "subscriptions", "notifications"}


def test_all_tables_registered():
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_companies_columns():
    cols = {c.name for c in Base.metadata.tables["companies"].columns}
    assert cols == {
        "id",
        "user_id",
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
        "company_id",
        "google_metadata",
        "created_at",
        "updated_at",
    }


def test_subscriptions_columns():
    cols = {c.name for c in Base.metadata.tables["subscriptions"].columns}
    assert cols == {
        "id",
        "company_id",
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


def test_notifications_user_status_index():
    table = Base.metadata.tables["notifications"]
    index_names = {idx.name for idx in table.indexes}
    assert "idx_notifications_user_status" in index_names
