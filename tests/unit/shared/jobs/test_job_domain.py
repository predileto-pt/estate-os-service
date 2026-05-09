from uuid import uuid4

import pytest

from shared.jobs.domain.exceptions import InvalidJobTransitionError
from shared.jobs.domain.job import Job, JobEntityType, JobKind, JobStatus


def _make_job() -> Job:
    return Job(
        id=uuid4(),
        organization_id=uuid4(),
        requested_by_user_id=uuid4(),
        kind=JobKind.PROPERTY_ENRICHMENT,
        entity_type=JobEntityType.PROPERTY,
        entity_id=uuid4(),
        title="Test job",
    )


def test_starts_in_processing():
    job = _make_job()
    assert job.status == JobStatus.PROCESSING
    assert job.completed_at is None


def test_complete_transitions_to_completed():
    job = _make_job()
    job.mark_completed({"foo": "bar"})
    assert job.status == JobStatus.COMPLETED
    assert job.result_summary == {"foo": "bar"}
    assert job.completed_at is not None


def test_fail_transitions_to_failed():
    job = _make_job()
    job.mark_failed(error_code="boom", error_message="provider down")
    assert job.status == JobStatus.FAILED
    assert job.error_code == "boom"
    assert job.error_message == "provider down"
    assert job.completed_at is not None


def test_complete_after_complete_is_noop():
    job = _make_job()
    job.mark_completed({"first": True})
    first_updated = job.updated_at
    job.mark_completed({"second": True})
    # No-op — result_summary stays the first one, updated_at unchanged.
    assert job.result_summary == {"first": True}
    assert job.updated_at == first_updated


def test_fail_after_fail_is_noop():
    job = _make_job()
    job.mark_failed(error_code="x", error_message="first")
    first_updated = job.updated_at
    job.mark_failed(error_code="y", error_message="second")
    assert job.error_code == "x"
    assert job.error_message == "first"
    assert job.updated_at == first_updated


def test_complete_after_fail_raises():
    job = _make_job()
    job.mark_failed(error_code="x", error_message="boom")
    with pytest.raises(InvalidJobTransitionError):
        job.mark_completed({})


def test_fail_after_complete_raises():
    job = _make_job()
    job.mark_completed({})
    with pytest.raises(InvalidJobTransitionError):
        job.mark_failed(error_code="x", error_message="boom")


def test_update_entity_id_succeeds_while_non_terminal():
    job = _make_job()
    new_entity = uuid4()
    job.update_entity_id(new_entity)
    assert job.entity_id == new_entity


def test_update_entity_id_raises_after_complete():
    job = _make_job()
    job.mark_completed({})
    with pytest.raises(InvalidJobTransitionError):
        job.update_entity_id(uuid4())


def test_update_entity_id_raises_after_fail():
    job = _make_job()
    job.mark_failed(error_code="x", error_message="boom")
    with pytest.raises(InvalidJobTransitionError):
        job.update_entity_id(uuid4())
