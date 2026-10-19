"""Test job lifecycle: acceptance, asynchronous execution, status polling, and persistence."""

import asyncio
from pathlib import Path
import httpx
import pytest

from incubrix.config import settings
from incubrix.storage import IdempotencyManager, JobStore


@pytest.mark.asyncio
async def test_job_submission_and_lifecycle(client: httpx.AsyncClient):
    """Verify entire happy-path lifecycle: POST 202 -> running -> succeeded."""
    headers = {
        "Idempotency-Key": "lifecycle-key-001",
        "X-Correlation-Id": "11111111-2222-3333-4444-555555555555",
    }
    payload = {
        "script": "Saving money starts with tracking expenses carefully.",
        "aspect_ratios": ["16:9", "9:16"],
        "voice": "en-IN-female",
        "style": "modern, clean",
        "avoid": ["faces"],
        "captions": {"burn_in": True, "srt": True},
    }

    # 1. POST returns 202 immediately
    res_post = await client.post("/api/v1/broll/jobs", json=payload, headers=headers)
    assert res_post.status_code == 202
    assert "Location" in res_post.headers
    assert res_post.headers["X-Correlation-Id"] == "11111111-2222-3333-4444-555555555555"

    data = res_post.json()
    job_id = data["job_id"]
    assert job_id.startswith("job_")
    assert data["status"] in ["queued", "running"]
    assert data["urls"]["status_url"] == f"/api/v1/jobs/{job_id}"

    # 2. Poll GET /api/v1/jobs/{job_id} until terminal state
    max_wait_seconds = 10
    interval = 0.1
    elapsed = 0.0
    final_status = None

    while elapsed < max_wait_seconds:
        res_get = await client.get(f"/api/v1/jobs/{job_id}")
        assert res_get.status_code == 200
        job_data = res_get.json()
        assert job_data["job_id"] == job_id

        if job_data["status"] == "succeeded":
            final_status = job_data
            break
        elif job_data["status"] == "failed":
            pytest.fail(f"Job unexpectedly failed: {job_data.get('error')}")

        await asyncio.sleep(interval)
        elapsed += interval

    assert final_status is not None, "Job did not complete within timeout"
    assert final_status["status"] == "succeeded"
    assert final_status["progress"] == 100
    assert final_status["stage"] == "completed"
    assert final_status["started_at"] is not None
    assert final_status["completed_at"] is not None
    assert final_status["duration_seconds"] is not None

    # 3. Verify Artifacts
    artifacts = final_status["artifacts"]
    assert "videos" in artifacts
    assert "16:9" in artifacts["videos"]
    assert "9:16" in artifacts["videos"]
    assert "captions" in artifacts
    assert "timeline" in artifacts
    assert "manifest" in artifacts

    # 4. Verify alias route /api/v1/broll/jobs/{job_id}
    res_alias = await client.get(f"/api/v1/broll/jobs/{job_id}")
    assert res_alias.status_code == 200
    assert res_alias.json() == final_status

    # 5. Verify artifact file retrieval endpoint
    res_captions = await client.get(f"/api/v1/jobs/{job_id}/artifacts/captions.srt")
    assert res_captions.status_code == 200
    assert "00:00:00,000" in res_captions.text


@pytest.mark.asyncio
async def test_job_persistence_across_restart(client: httpx.AsyncClient, isolated_storage):
    """Job records and generated files survive worker restarts."""
    headers = {"Idempotency-Key": "persistence-test-002"}
    payload = {"script": "Testing persistent storage state survival."}

    res = await client.post("/api/v1/broll/jobs", json=payload, headers=headers)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    # Wait for completion
    for _ in range(50):
        res_get = await client.get(f"/api/v1/jobs/{job_id}")
        if res_get.json()["status"] == "succeeded":
            break
        await asyncio.sleep(0.1)

    # Simulate container/worker restart by instantiating a new JobStore on the same directory
    restarted_idemp = IdempotencyManager(file_path=isolated_storage["idemp_file"])
    restarted_store = JobStore(jobs_dir=isolated_storage["jobs_dir"], idempotency_manager=restarted_idemp)

    # Load job from new store instance
    reloaded_job = restarted_store.get_job_sync(job_id)
    assert reloaded_job is not None
    assert reloaded_job.job_id == job_id
    assert reloaded_job.status == "succeeded"
    assert reloaded_job.progress == 100
    assert (isolated_storage["jobs_dir"] / job_id / "job.json").exists()
    assert (isolated_storage["jobs_dir"] / job_id / "artifacts" / "timeline.json").exists()
