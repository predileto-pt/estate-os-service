class TestSubmitBatchExtractionEndpoint:
    async def test_submit_batch_returns_202(self, client, auth_headers, document_storage):
        # First get presigned URLs
        presign_resp = await client.post(
            "/api/v1/extraction-jobs/presign",
            json={
                "files": [
                    {"filename": "escritura.pdf", "content_type": "application/pdf"},
                    {"filename": "cc_owner1.pdf", "content_type": "application/pdf"},
                ]
            },
            headers=auth_headers,
        )
        data = presign_resp.json()
        job_id = data["job_id"]
        s3_keys = [f["s3_key"] for f in data["files"]]

        # Simulate upload
        for key in s3_keys:
            await document_storage.upload(key, b"fake-pdf", "application/pdf")

        # Submit batch
        response = await client.post(
            "/api/v1/extraction-jobs/batch",
            json={
                "job_id": job_id,
                "document_keys": s3_keys,
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )
        assert response.status_code == 202
        result = response.json()
        assert result["status"] == "pending"
        assert len(result["document_keys"]) == 2
        assert result["listing_type"] == "sale"
        assert result["typology"] == "apartment"

    async def test_submit_batch_missing_document(self, client, auth_headers):
        job_id = "11111111-1111-1111-1111-111111111111"
        response = await client.post(
            "/api/v1/extraction-jobs/batch",
            json={
                "job_id": job_id,
                "document_keys": [f"extractions/{job_id}/0.pdf"],
                "listing_type": "sale",
                "typology": "house",
            },
            headers=auth_headers,
        )
        assert response.status_code == 404

    async def test_submit_batch_requires_auth(self, client):
        response = await client.post(
            "/api/v1/extraction-jobs/batch",
            json={
                "job_id": "test",
                "document_keys": ["key"],
                "listing_type": "sale",
                "typology": "house",
            },
        )
        assert response.status_code == 401

    async def test_batch_job_appears_in_list(self, client, auth_headers, document_storage):
        # Presign + upload + submit batch
        presign_resp = await client.post(
            "/api/v1/extraction-jobs/presign",
            json={"files": [{"filename": "test.pdf"}]},
            headers=auth_headers,
        )
        data = presign_resp.json()
        s3_key = data["files"][0]["s3_key"]
        await document_storage.upload(s3_key, b"fake-pdf", "application/pdf")

        await client.post(
            "/api/v1/extraction-jobs/batch",
            json={
                "job_id": data["job_id"],
                "document_keys": [s3_key],
                "listing_type": "sale",
                "typology": "apartment",
            },
            headers=auth_headers,
        )

        # Should appear in list
        response = await client.get(
            "/api/v1/extraction-jobs/",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_batch_job_retrievable_by_id(self, client, auth_headers, document_storage):
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
            "/api/v1/extraction-jobs/batch",
            json={
                "job_id": job_id,
                "document_keys": [s3_key],
                "listing_type": "purchase",
                "typology": "house",
            },
            headers=auth_headers,
        )

        response = await client.get(
            f"/api/v1/extraction-jobs/{job_id}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == job_id
        assert response.json()["listing_type"] == "purchase"
        assert response.json()["typology"] == "house"
