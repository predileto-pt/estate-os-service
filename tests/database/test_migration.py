from sqlalchemy import text


async def test_current_revision_is_head(session):
    result = await session.execute(text("SELECT version_num FROM alembic_version"))
    row = result.first()
    assert row is not None
    assert row[0] == "086bbeedc7ab"


async def test_all_tables_exist(session):
    result = await session.execute(
        text("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    )
    tables = {row[0] for row in result.fetchall()}
    expected = {
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
        "property_prices",
        "property_images",
    }
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


async def test_updated_at_trigger_exists(session):
    result = await session.execute(
        text("""
        SELECT trigger_name, event_object_table FROM information_schema.triggers
        WHERE trigger_schema = 'public'
        ORDER BY trigger_name
    """)
    )
    triggers = {(row[0], row[1]) for row in result.fetchall()}
    assert ("set_updated_at_memberships", "memberships") in triggers
    assert ("trg_users_updated_at", "users") in triggers
    assert ("trg_subscriptions_updated_at", "subscriptions") in triggers
    assert ("trg_properties_updated_at", "properties") in triggers
    assert ("trg_property_owners_updated_at", "property_owners") in triggers
    assert ("trg_property_prices_updated_at", "property_prices") in triggers
    assert ("update_property_images_updated_at", "property_images") in triggers
