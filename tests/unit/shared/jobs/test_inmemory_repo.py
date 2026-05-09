from uuid import uuid4

import pytest

from shared.jobs.adapters.persistence.inmemory_job_repository import (
    InMemoryJobRepository,
)
from shared.jobs.domain.job import Job, JobEntityType, JobKind, JobStatus


def _make_job(**overrides) -> Job:
    defaults = dict(
        id=uuid4(),
        organization_id=uuid4(),
        requested_by_user_id=uuid4(),
        kind=JobKind.PROPERTY_ENRICHMENT,
        entity_type=JobEntityType.PROPERTY,
        entity_id=uuid4(),
        title="Test",
    )
    defaults.update(overrides)
    return Job(**defaults)


async def test_insert_and_get_by_id():
    repo = InMemoryJobRepository()
    job = _make_job()
    await repo.insert(job)
    fetched = await repo.get_by_id(job.id)
    assert fetched is not None
    assert fetched.id == job.id
    assert fetched.title == "Test"


async def test_get_by_id_missing_returns_none():
    repo = InMemoryJobRepository()
    assert await repo.get_by_id(uuid4()) is None


async def test_update_persists():
    repo = InMemoryJobRepository()
    job = _make_job()
    await repo.insert(job)
    job.mark_completed({"ok": True})
    await repo.update(job)
    fetched = await repo.get_by_id(job.id)
    assert fetched.status == JobStatus.COMPLETED
    assert fetched.result_summary == {"ok": True}


async def test_update_missing_raises():
    repo = InMemoryJobRepository()
    with pytest.raises(KeyError):
        await repo.update(_make_job())


async def test_list_filters_by_organization():
    repo = InMemoryJobRepository()
    org_a = uuid4()
    org_b = uuid4()
    job_a = _make_job(organization_id=org_a)
    job_b = _make_job(organization_id=org_b)
    await repo.insert(job_a)
    await repo.insert(job_b)
    rows = await repo.list(organization_id=org_a)
    assert len(rows) == 1
    assert rows[0].id == job_a.id


async def test_list_filters_by_status():
    repo = InMemoryJobRepository()
    org = uuid4()
    a = _make_job(organization_id=org)
    b = _make_job(organization_id=org)
    await repo.insert(a)
    await repo.insert(b)
    a.mark_completed({})
    await repo.update(a)
    rows = await repo.list(organization_id=org, statuses=[JobStatus.PROCESSING])
    assert len(rows) == 1
    assert rows[0].id == b.id


async def test_list_filters_by_entity():
    repo = InMemoryJobRepository()
    org = uuid4()
    target = uuid4()
    other = uuid4()
    a = _make_job(organization_id=org, entity_id=target)
    b = _make_job(organization_id=org, entity_id=other)
    await repo.insert(a)
    await repo.insert(b)
    rows = await repo.list(
        organization_id=org,
        entity_type=JobEntityType.PROPERTY,
        entity_id=target,
    )
    assert len(rows) == 1
    assert rows[0].id == a.id


async def test_list_orders_by_created_at_desc_and_respects_limit():
    repo = InMemoryJobRepository()
    org = uuid4()
    jobs = [_make_job(organization_id=org) for _ in range(5)]
    # Insert with monotonically increasing created_at to make ordering
    # deterministic.
    for i, job in enumerate(jobs):
        from datetime import datetime, timezone, timedelta

        job.created_at = datetime.now(timezone.utc) + timedelta(seconds=i)
        await repo.insert(job)
    rows = await repo.list(organization_id=org, limit=3)
    assert len(rows) == 3
    # Most recent first.
    assert rows[0].id == jobs[4].id
    assert rows[1].id == jobs[3].id
    assert rows[2].id == jobs[2].id
