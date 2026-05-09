"""Integration tests for GET /api/v1/admin/properties/{id}/jobs.

Convenience route layered over shared `ListJobs` (ADR-012). Filters by
`(entity_type=PROPERTY, entity_id=property_id)` automatically.
"""

from uuid import uuid4

import pytest

from shared.jobs.domain.job import JobEntityType, JobKind
from tests.conftest import TEST_ORGANIZATION_ID


@pytest.fixture(autouse=True)
def _auto_seed_member(seed_test_member):
    return seed_test_member


async def _seed(
    job_tracker,
    *,
    entity_id,
    organization_id=TEST_ORGANIZATION_ID,
    kind=JobKind.PROPERTY_ENRICHMENT,
    title="Job",
):
    return await job_tracker.start(
        organization_id=uuid4().__class__(organization_id),
        requested_by_user_id=uuid4(),
        kind=kind,
        entity_type=JobEntityType.PROPERTY,
        entity_id=entity_id,
        title=title,
    )


async def test_returns_only_jobs_for_this_property(client, auth_headers, job_tracker):
    target = uuid4()
    other = uuid4()
    target_job = await _seed(job_tracker, entity_id=target, title="Target")
    await _seed(job_tracker, entity_id=other, title="Other")

    response = await client.get(
        f"/api/v1/admin/properties/{target}/jobs?organization_id={TEST_ORGANIZATION_ID}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == str(target_job)
    assert data[0]["title"] == "Target"


async def test_filters_by_kind(client, auth_headers, job_tracker):
    target = uuid4()
    enrichment_id = await _seed(job_tracker, entity_id=target, kind=JobKind.PROPERTY_ENRICHMENT)
    await _seed(job_tracker, entity_id=target, kind=JobKind.PROPERTY_DOCUMENT_EXTRACTION)

    response = await client.get(
        f"/api/v1/admin/properties/{target}/jobs?organization_id={TEST_ORGANIZATION_ID}"
        f"&kind={JobKind.PROPERTY_ENRICHMENT.value}",
        headers=auth_headers,
    )
    data = response.json()
    assert len(data) == 1
    assert data[0]["id"] == str(enrichment_id)


async def test_limit_out_of_range_returns_422(client, auth_headers):
    target = uuid4()
    for bad in (0, -1, 51):
        response = await client.get(
            f"/api/v1/admin/properties/{target}/jobs"
            f"?organization_id={TEST_ORGANIZATION_ID}&limit={bad}",
            headers=auth_headers,
        )
        assert response.status_code == 422


async def test_non_member_returns_403(client, auth_headers):
    target = uuid4()
    response = await client.get(
        f"/api/v1/admin/properties/{target}/jobs"
        "?organization_id=00000000-0000-0000-0000-000000000099",
        headers=auth_headers,
    )
    assert response.status_code == 403
