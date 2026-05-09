"""Integration tests for the shared jobs routes (ADR-012).

GET /api/v1/admin/jobs — list with filters.
GET /api/v1/admin/jobs/{id} — single record.
"""

from uuid import uuid4

import pytest

from shared.jobs.domain.job import JobEntityType, JobKind
from tests.conftest import TEST_ORGANIZATION_ID

OTHER_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture(autouse=True)
def _auto_seed_member(seed_test_member):
    return seed_test_member


async def _seed_job(
    job_tracker,
    *,
    organization_id: str = TEST_ORGANIZATION_ID,
    kind: JobKind = JobKind.PROPERTY_ENRICHMENT,
    entity_id=None,
    title: str = "Test job",
):
    return await job_tracker.start(
        organization_id=uuid4().__class__(organization_id),
        requested_by_user_id=uuid4(),
        kind=kind,
        entity_type=JobEntityType.PROPERTY,
        entity_id=entity_id or uuid4(),
        title=title,
    )


class TestListJobs:
    async def test_list_returns_recent_first(self, client, auth_headers, job_tracker):
        await _seed_job(job_tracker, title="Older")
        latest_id = await _seed_job(job_tracker, title="Newest")

        response = await client.get(
            f"/api/v1/admin/jobs/?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["id"] == str(latest_id)
        assert data[0]["title"] == "Newest"

    async def test_list_filters_by_kind(self, client, auth_headers, job_tracker):
        await _seed_job(job_tracker, kind=JobKind.PROPERTY_DOCUMENT_EXTRACTION)
        enrichment_id = await _seed_job(job_tracker, kind=JobKind.PROPERTY_ENRICHMENT)

        response = await client.get(
            f"/api/v1/admin/jobs/?organization_id={TEST_ORGANIZATION_ID}"
            f"&kind={JobKind.PROPERTY_ENRICHMENT.value}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == str(enrichment_id)

    async def test_list_filters_by_status(self, client, auth_headers, job_tracker):
        completed_id = await _seed_job(job_tracker)
        await job_tracker.complete(completed_id)
        processing_id = await _seed_job(job_tracker)

        response = await client.get(
            f"/api/v1/admin/jobs/?organization_id={TEST_ORGANIZATION_ID}&status=processing",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == str(processing_id)

    async def test_list_status_accepts_comma_separated(self, client, auth_headers, job_tracker):
        completed_id = await _seed_job(job_tracker)
        await job_tracker.complete(completed_id)
        processing_id = await _seed_job(job_tracker)

        response = await client.get(
            f"/api/v1/admin/jobs/?organization_id={TEST_ORGANIZATION_ID}"
            "&status=processing,completed",
            headers=auth_headers,
        )
        data = response.json()
        ids = {row["id"] for row in data}
        assert ids == {str(completed_id), str(processing_id)}

    async def test_list_cross_org_isolation(self, client, auth_headers, job_tracker):
        """ACR: a caller seeing org X's jobs MUST NOT see org Y's even if
        the caller is a member of both."""
        # Seed one in our org, one in a different org.
        await _seed_job(job_tracker, organization_id=TEST_ORGANIZATION_ID)
        await _seed_job(job_tracker, organization_id=OTHER_ORGANIZATION_ID)

        response = await client.get(
            f"/api/v1/admin/jobs/?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        data = response.json()
        assert len(data) == 1
        assert data[0]["organization_id"] == TEST_ORGANIZATION_ID

    async def test_list_limit_default_10(self, client, auth_headers, job_tracker):
        for i in range(15):
            await _seed_job(job_tracker, title=f"job-{i}")
        response = await client.get(
            f"/api/v1/admin/jobs/?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert len(response.json()) == 10

    async def test_list_limit_max_50(self, client, auth_headers, job_tracker):
        for i in range(60):
            await _seed_job(job_tracker, title=f"job-{i}")
        response = await client.get(
            f"/api/v1/admin/jobs/?organization_id={TEST_ORGANIZATION_ID}&limit=50",
            headers=auth_headers,
        )
        assert len(response.json()) == 50

    async def test_list_limit_out_of_range_returns_422(self, client, auth_headers):
        for bad in (0, -1, 51):
            response = await client.get(
                f"/api/v1/admin/jobs/?organization_id={TEST_ORGANIZATION_ID}&limit={bad}",
                headers=auth_headers,
            )
            assert response.status_code == 422

    async def test_list_unauthenticated_401(self, client):
        response = await client.get(f"/api/v1/admin/jobs/?organization_id={TEST_ORGANIZATION_ID}")
        assert response.status_code == 401

    async def test_list_non_member_403(self, client, auth_headers):
        response = await client.get(
            f"/api/v1/admin/jobs/?organization_id={OTHER_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 403


class TestGetJob:
    async def test_get_happy_path(self, client, auth_headers, job_tracker):
        job_id = await _seed_job(job_tracker, title="Specific")
        response = await client.get(
            f"/api/v1/admin/jobs/{job_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == str(job_id)
        assert body["title"] == "Specific"
        assert body["status"] == "processing"

    async def test_get_unknown_returns_404(self, client, auth_headers):
        bogus = "00000000-0000-0000-0000-0000000000ff"
        response = await client.get(
            f"/api/v1/admin/jobs/{bogus}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_get_cross_org_returns_404_not_403(self, client, auth_headers, job_tracker):
        """ACR: a row that exists in org Y must look indistinguishable from
        'not found' to a caller asking via org X — prevents existence leaks."""
        other_org_job_id = await _seed_job(job_tracker, organization_id=OTHER_ORGANIZATION_ID)
        # Caller IS a member of TEST_ORGANIZATION_ID and asks via that org.
        response = await client.get(
            f"/api/v1/admin/jobs/{other_org_job_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 404
