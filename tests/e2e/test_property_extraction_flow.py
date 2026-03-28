import json

import pytest


async def _register_user(client, auth_headers):
    response = await client.post(
        "/api/v1/admin/auth/register",
        json={
            "name": "Property Owner",
            "email": "property@e2e-test.pt",
            "organization_name": "E2E Properties",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.e2e
async def test_presign_upload_and_submit_extraction(
    client, auth_headers, sqs_client, sqs_queue_url
):
    user_data = await _register_user(client, auth_headers)
    org_id = user_data.get("organization_id", "")

    # Generate presigned upload URL
    presign_resp = await client.post(
        "/api/v1/admin/extraction-jobs/presign",
        json={
            "files": [
                {"filename": "escritura.pdf", "content_type": "application/pdf"},
            ]
        },
        headers=auth_headers,
    )
    assert presign_resp.status_code == 200
    presign_data = presign_resp.json()
    assert len(presign_data["files"]) == 1
    assert "upload_url" in presign_data["files"][0]
    s3_key = presign_data["files"][0]["s3_key"]
    job_id = presign_data["job_id"]

    # Upload to real S3 via presigned URL
    import httpx

    upload_url = presign_data["files"][0]["upload_url"]
    async with httpx.AsyncClient() as upload_client:
        upload_resp = await upload_client.put(
            upload_url,
            content=b"fake pdf content for e2e test",
            headers={"Content-Type": "application/pdf"},
        )
        assert upload_resp.status_code == 200

    # Submit extraction job
    submit_resp = await client.post(
        "/api/v1/admin/extraction-jobs/",
        json={
            "job_id": job_id,
            "organization_id": org_id,
            "document_keys": [s3_key],
            "listing_type": "sale",
            "typology": "apartment",
        },
        headers=auth_headers,
    )
    assert submit_resp.status_code == 202
    job_data = submit_resp.json()
    assert job_data["status"] == "pending"

    # Verify SQS message was published
    response = sqs_client.receive_message(
        QueueUrl=sqs_queue_url,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=5,
    )
    messages = response.get("Messages", [])
    assert len(messages) >= 1

    bodies = [json.loads(m["Body"]) for m in messages]
    job_messages = [b for b in bodies if b.get("data", {}).get("job_id") == str(job_data["id"])]
    assert len(job_messages) >= 1


@pytest.mark.e2e
async def test_list_extraction_jobs(client, auth_headers):
    user_data = await _register_user(client, auth_headers)
    org_id = user_data.get("organization_id", "")

    list_resp = await client.get(
        f"/api/v1/admin/extraction-jobs/?organization_id={org_id}", headers=auth_headers
    )
    assert list_resp.status_code == 200
    assert isinstance(list_resp.json(), list)
