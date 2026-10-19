"""Test Idempotency-Key behavior, safe retries, and conflict detection."""

import pytest
import httpx


@pytest.mark.asyncio
async def test_idempotent_retry_returns_same_job(client: httpx.AsyncClient):
    """Submitting the same payload with the same Idempotency-Key returns the existing job."""
    headers = {"Idempotency-Key": "idemp-key-repeatable-001"}
    payload = {
        "script": "Saving money doesn't have to be complicated.",
        "aspect_ratios": ["16:9"],
        "voice": "en-IN-female",
    }

    # First submission
    res1 = await client.post("/api/v1/broll/jobs", json=payload, headers=headers)
    assert res1.status_code == 202
    data1 = res1.json()
    job_id_1 = data1["job_id"]
    assert job_id_1.startswith("job_")

    # Resubmission with same key and same payload
    res2 = await client.post("/api/v1/broll/jobs", json=payload, headers=headers)
    assert res2.status_code == 202
    data2 = res2.json()
    job_id_2 = data2["job_id"]

    # Must return the same job_id without creating a new job
    assert job_id_1 == job_id_2
    assert data1["created_at"] == data2["created_at"]


@pytest.mark.asyncio
async def test_idempotent_conflict_on_different_payload(client: httpx.AsyncClient):
    """Submitting different payload with already used Idempotency-Key returns 409 Conflict."""
    headers = {"Idempotency-Key": "idemp-key-conflict-002"}
    payload1 = {
        "script": "First submission text.",
        "aspect_ratios": ["16:9"],
    }
    payload2 = {
        "script": "Different second submission text.",
        "aspect_ratios": ["9:16"],
    }

    # First submission succeeds
    res1 = await client.post("/api/v1/broll/jobs", json=payload1, headers=headers)
    assert res1.status_code == 202

    # Second submission with same key but differing payload fails with 409
    res2 = await client.post("/api/v1/broll/jobs", json=payload2, headers=headers)
    assert res2.status_code == 409
    body = res2.json()
    assert body["error"]["code"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert body["error"]["retryable"] is False
