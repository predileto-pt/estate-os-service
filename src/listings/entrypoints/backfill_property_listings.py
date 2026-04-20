"""One-shot CLI: replay every existing Property as a synthetic
`PROPERTY_CREATED.v1` event so the new `property_listings` table can
be populated for rows that pre-date this spec.

Run once after `alembic upgrade head` creates the `property_listings`
table and the listings events_worker is running:

    uv run python -m listings.entrypoints.backfill_property_listings

The CLI doesn't touch the `property_listings` table directly. It
publishes to the `PROPERTY_CREATED.v1` SNS topic — SNS fans out to the
listings queue — the projector picks each event up and upserts a row —
the enrichment handler fills parish/municipality/district. Same code
path as normal operation, tested by the integration suite.

Properties are walked in batches via the existing
`PropertyRepository.list_by_organization` aggregated across all
organizations. For each Property, the aggregate_version is bumped to
`max(current, 1)` so the synthetic event doesn't regress newer events
already published to listings — the projector's
`source_aggregate_version` guard catches this and drops the synthetic
if the real row is newer.
"""

import asyncio

import aioboto3
import structlog

from properties.application.events.property_event import build_property_snapshot
from shared.config import Settings, setup_logging
from shared.entrypoints.bootstrap import get_container, get_property_container
from shared.events.adapters.sns_event_publisher import SNSEventPublisher
from shared.events.base import DomainEvent
from shared.events.types import PROPERTY_CREATED_V1

log = structlog.get_logger()


async def _backfill() -> None:
    settings = Settings()
    setup_logging(settings.log_level)

    session = aioboto3.Session(
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        region_name=settings.aws_region,
    )
    publisher = SNSEventPublisher(
        session=session,
        topic_arn_prefix=settings.sns_domain_events_topic_arn_prefix,
        endpoint_url=settings.aws_endpoint_url,
    )

    orgs_container = await get_container()
    properties_container = await get_property_container()

    total = 0
    failed = 0

    # Walk orgs → properties. `list_by_user` on the membership repo
    # gives us org_ids the way prod code already does — reusing the
    # established surface rather than adding a new "list all orgs" port.
    orgs = (
        await orgs_container.organization_repo.list_all()
        if hasattr(orgs_container.organization_repo, "list_all")
        else []
    )
    if not orgs:
        log.warning(
            "backfill.no_list_all_method",
            message=(
                "OrganizationRepository has no list_all; walking memberships "
                "instead. For very large accounts, add a dedicated iterator."
            ),
        )
        # Conservative fallback: walk the memberships table. Every
        # property has an org; every org has at least one membership.
        memberships = (
            await orgs_container.membership_repo.list_all()
            if hasattr(orgs_container.membership_repo, "list_all")
            else []
        )
        org_ids = {m.organization_id for m in memberships}
    else:
        org_ids = {o.id for o in orgs}

    for org_id in org_ids:
        properties = await properties_container.property_repo.list_by_organization(org_id)
        for prop in properties:
            try:
                # Guarantee aggregate_version >= 1 so the projector's
                # version guard accepts the synthetic event on first
                # sight. Real subsequent events bump from here.
                if prop.aggregate_version < 1:
                    prop.aggregate_version = 1
                await publisher.publish(
                    DomainEvent(
                        event_type=PROPERTY_CREATED_V1,
                        data=build_property_snapshot(prop),
                    )
                )
                total += 1
            except Exception:
                failed += 1
                log.exception("backfill.publish_failed", property_id=str(prop.id))

    log.info("backfill.completed", total=total, failed=failed)


def main() -> None:
    asyncio.run(_backfill())


if __name__ == "__main__":
    main()
