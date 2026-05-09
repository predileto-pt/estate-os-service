from uuid import uuid4

import pytest

from shared.jobs.adapters.persistence.inmemory_job_repository import (
    InMemoryJobRepository,
)
from shared.jobs.adapters.tracking.default_job_tracker import DefaultJobTracker
from shared.jobs.domain.exceptions import InvalidJobTransitionError, JobNotFoundError
from shared.jobs.domain.job import JobEntityType, JobKind, JobStatus


async def _make_tracker():
    repo = InMemoryJobRepository()
    return DefaultJobTracker(repo), repo


async def _start_typical(tracker):
    return await tracker.start(
        organization_id=uuid4(),
        requested_by_user_id=uuid4(),
        kind=JobKind.PROPERTY_ENRICHMENT,
        entity_type=JobEntityType.PROPERTY,
        entity_id=uuid4(),
        title="Test",
    )


async def test_start_creates_processing_row():
    tracker, repo = await _make_tracker()
    job_id = await _start_typical(tracker)
    job = await repo.get_by_id(job_id)
    assert job is not None
    assert job.status == JobStatus.PROCESSING


async def test_complete_idempotent_on_completed():
    tracker, repo = await _make_tracker()
    job_id = await _start_typical(tracker)
    await tracker.complete(job_id, {"ok": True})
    # Second call: no-op, doesn't raise.
    await tracker.complete(job_id, {"second": True})
    job = await repo.get_by_id(job_id)
    assert job.result_summary == {"ok": True}


async def test_fail_idempotent_on_failed():
    tracker, repo = await _make_tracker()
    job_id = await _start_typical(tracker)
    await tracker.fail(job_id, error_code="x", error_message="boom")
    await tracker.fail(job_id, error_code="y", error_message="second")
    job = await repo.get_by_id(job_id)
    assert job.error_code == "x"


async def test_complete_after_fail_raises():
    tracker, _ = await _make_tracker()
    job_id = await _start_typical(tracker)
    await tracker.fail(job_id, error_code="x", error_message="boom")
    with pytest.raises(InvalidJobTransitionError):
        await tracker.complete(job_id)


async def test_update_entity_id_repoints_row():
    tracker, repo = await _make_tracker()
    job_id = await _start_typical(tracker)
    new_entity = uuid4()
    await tracker.update_entity_id(job_id, new_entity)
    job = await repo.get_by_id(job_id)
    assert job.entity_id == new_entity


async def test_update_entity_id_raises_after_complete():
    tracker, _ = await _make_tracker()
    job_id = await _start_typical(tracker)
    await tracker.complete(job_id)
    with pytest.raises(InvalidJobTransitionError):
        await tracker.update_entity_id(job_id, uuid4())


async def test_complete_unknown_id_raises():
    tracker, _ = await _make_tracker()
    with pytest.raises(JobNotFoundError):
        await tracker.complete(uuid4())


async def test_fail_unknown_id_raises():
    tracker, _ = await _make_tracker()
    with pytest.raises(JobNotFoundError):
        await tracker.fail(uuid4(), error_code="x", error_message="boom")


async def test_update_entity_id_unknown_id_raises():
    tracker, _ = await _make_tracker()
    with pytest.raises(JobNotFoundError):
        await tracker.update_entity_id(uuid4(), uuid4())


async def test_result_summary_soft_cap_truncates():
    """Payloads over 4KB are stored as a truncation marker (CompleteJob)."""
    import structlog

    tracker, repo = await _make_tracker()
    job_id = await _start_typical(tracker)
    big_summary = {"data": "x" * 5000}
    with structlog.testing.capture_logs() as caplog:
        await tracker.complete(job_id, big_summary)
    job = await repo.get_by_id(job_id)
    assert job.result_summary is not None
    assert job.result_summary.get("_truncated") is True
    assert any(e.get("event") == "jobs.result_summary_truncated" for e in caplog)
