from tests.conftest import TEST_ORGANIZATION_ID


class TestPresignEndpoint:
    async def test_presign_returns_urls(self, client, auth_headers):
        response = await client.post(
            "/api/v1/extraction-jobs/presign",
            json={
                "files": [
                    {"filename": "escritura.pdf", "content_type": "application/pdf"},
                    {"filename": "caderneta.pdf", "content_type": "application/pdf"},
                ]
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert len(data["files"]) == 2
        assert data["files"][0]["s3_key"].startswith(f"extractions/{data['job_id']}/")
        assert "upload_url" in data["files"][0]

    async def test_presign_requires_auth(self, client):
        response = await client.post(
            "/api/v1/extraction-jobs/presign",
            json={"files": [{"filename": "test.pdf"}]},
        )
        assert response.status_code == 401

    async def test_presign_empty_files(self, client, auth_headers):
        response = await client.post(
            "/api/v1/extraction-jobs/presign",
            json={"files": []},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_presign_too_many_files(self, client, auth_headers):
        files = [{"filename": f"doc{i}.pdf"} for i in range(6)]
        response = await client.post(
            "/api/v1/extraction-jobs/presign",
            json={"files": files},
            headers=auth_headers,
        )
        assert response.status_code == 422


class TestSubmitExtractionEndpoint:
    async def test_submit_returns_202(self, client, auth_headers, document_storage):
        # First get presigned URLs
        presign_resp = await client.post(
            "/api/v1/extraction-jobs/presign",
            json={"files": [{"filename": "test.pdf"}]},
            headers=auth_headers,
        )
        data = presign_resp.json()
        job_id = data["job_id"]
        s3_key = data["files"][0]["s3_key"]

        # Simulate upload
        await document_storage.upload(s3_key, b"fake-pdf", "application/pdf")

        # Submit
        response = await client.post(
            "/api/v1/extraction-jobs/",
            json={
                "job_id": job_id,
                "organization_id": TEST_ORGANIZATION_ID,
                "document_keys": [s3_key],
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        assert response.status_code == 202
        result = response.json()
        assert result["status"] == "pending"
        assert result["document_keys"] == [s3_key]
        assert result["listing_type"] == "sale"
        assert result["typology"] == "apartment"
        assert result["organization_id"] == TEST_ORGANIZATION_ID

    async def test_submit_missing_document(self, client, auth_headers):
        job_id = "11111111-1111-1111-1111-111111111111"
        response = await client.post(
            "/api/v1/extraction-jobs/",
            json={
                "job_id": job_id,
                "organization_id": TEST_ORGANIZATION_ID,
                "document_keys": [f"extractions/{job_id}/0.pdf"],
                "listing_type": "sale",
                "typology": "house",
            },
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_submit_requires_auth(self, client):
        response = await client.post(
            "/api/v1/extraction-jobs/",
            json={
                "job_id": "test",
                "organization_id": TEST_ORGANIZATION_ID,
                "document_keys": ["key"],
                "listing_type": "sale",
                "typology": "house",
            },
        )
        assert response.status_code == 401


class TestListExtractionJobs:
    async def test_list_empty(self, client, auth_headers):
        response = await client.get(
            f"/api/v1/extraction-jobs/?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_after_submit(self, client, auth_headers, document_storage):
        # Presign + upload + submit
        presign_resp = await client.post(
            "/api/v1/extraction-jobs/presign",
            json={"files": [{"filename": "test.pdf"}]},
            headers=auth_headers,
        )
        data = presign_resp.json()
        s3_key = data["files"][0]["s3_key"]
        await document_storage.upload(s3_key, b"fake-pdf", "application/pdf")

        await client.post(
            "/api/v1/extraction-jobs/",
            json={
                "job_id": data["job_id"],
                "organization_id": TEST_ORGANIZATION_ID,
                "document_keys": [s3_key],
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/v1/extraction-jobs/?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert len(response.json()) == 1


class TestGetExtractionJob:
    async def test_get_job(self, client, auth_headers, document_storage):
        presign_resp = await client.post(
            "/api/v1/extraction-jobs/presign",
            json={"files": [{"filename": "test.pdf"}]},
            headers=auth_headers,
        )
        data = presign_resp.json()
        job_id = data["job_id"]
        s3_key = data["files"][0]["s3_key"]
        await document_storage.upload(s3_key, b"fake-pdf", "application/pdf")

        await client.post(
            "/api/v1/extraction-jobs/",
            json={
                "job_id": job_id,
                "organization_id": TEST_ORGANIZATION_ID,
                "document_keys": [s3_key],
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/v1/extraction-jobs/{job_id}?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == job_id

    async def test_get_nonexistent_job(self, client, auth_headers):
        response = await client.get(
            f"/api/v1/extraction-jobs/11111111-1111-1111-1111-111111111111?organization_id={TEST_ORGANIZATION_ID}",
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_get_job_requires_auth(self, client):
        response = await client.get(
            f"/api/v1/extraction-jobs/11111111-1111-1111-1111-111111111111?organization_id={TEST_ORGANIZATION_ID}",
        )
        assert response.status_code == 401
