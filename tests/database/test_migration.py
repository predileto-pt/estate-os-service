from sqlalchemy import text


async def test_current_revision_is_head(session):
    result = await session.execute(text("SELECT version_num FROM alembic_version"))
    row = result.first()
    assert row is not None
    assert row[0] == "c2c206f0a679"


async def test_property_listings_address_dropped_country_added(session):
    """Spec 2026-05-property-address-enrichment-fix v5:
    - DROP `address` (privacy)
    - DROP `postal_code` (LLM-input only — never stored)
    - ADD `country` (NOT NULL default 'Portugal'), `city`, `state`,
      `region` (all nullable)
    """
    result = await session.execute(
        text("""
        SELECT column_name, is_nullable, data_type, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'property_listings'
        ORDER BY column_name
    """)
    )
    cols = {row[0]: (row[1], row[2], row[3]) for row in result.fetchall()}

    # Both leak/transient columns gone.
    assert "address" not in cols
    assert "postal_code" not in cols, (
        "postal_code is an LLM-input signal only; must not be persisted"
    )

    # `country` is NOT NULL with default 'Portugal'.
    assert "country" in cols
    assert cols["country"][0] == "NO"
    assert cols["country"][1] == "text"
    assert cols["country"][2] is not None and "Portugal" in cols["country"][2]

    # Forward-scope columns exist and are nullable.
    for forward_col in ("city", "state", "region"):
        assert forward_col in cols, f"missing {forward_col}"
        assert cols[forward_col][0] == "YES", f"{forward_col} should be nullable"
        assert cols[forward_col][1] == "text"

    # parish/municipality/district stay nullable (per-country invariant
    # is enforced by the searcher, not the schema).
    for pt_col in ("parish", "municipality", "district"):
        assert cols[pt_col][0] == "YES", f"{pt_col} should remain nullable"


async def test_property_pois_has_place_details_columns(session):
    """Spec 2026-05-poi-rich-metadata: address (text nullable),
    image_urls (jsonb NOT NULL default '[]'), reviews (jsonb nullable)."""
    result = await session.execute(
        text("""
        SELECT column_name, is_nullable, data_type, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'property_pois'
          AND column_name IN ('address', 'image_urls', 'reviews')
        ORDER BY column_name
    """)
    )
    cols = {row[0]: (row[1], row[2], row[3]) for row in result.fetchall()}
    assert "address" in cols and cols["address"][0] == "YES" and cols["address"][1] == "text"
    assert "image_urls" in cols and cols["image_urls"][0] == "NO"
    assert cols["image_urls"][1] == "jsonb"
    assert cols["image_urls"][2] is not None and "[]" in cols["image_urls"][2]
    assert "reviews" in cols and cols["reviews"][0] == "YES" and cols["reviews"][1] == "jsonb"


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
        "background_jobs",
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
    assert ("update_background_jobs_updated_at", "background_jobs") in triggers


async def test_extraction_jobs_has_tracked_job_id(session):
    result = await session.execute(
        text("""
        SELECT column_name, is_nullable, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'extraction_jobs'
          AND column_name = 'tracked_job_id'
    """)
    )
    row = result.first()
    assert row is not None
    assert row[1] == "YES"  # nullable
    assert row[2] == "uuid"


async def test_background_jobs_indexes_exist(session):
    result = await session.execute(
        text("""
        SELECT indexname FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = 'background_jobs'
    """)
    )
    indexes = {row[0] for row in result.fetchall()}
    assert "idx_background_jobs_org_status_created" in indexes
    assert "idx_background_jobs_entity" in indexes
    assert "idx_background_jobs_kind_status_created" in indexes
