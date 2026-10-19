"""Integration test verifying real headless agy CLI execution."""

import asyncio
from pathlib import Path
import shutil

import httpx
import pytest

from incubrix.config import settings


@pytest.mark.asyncio
async def test_live_headless_agy_execution(client: httpx.AsyncClient, isolated_storage, monkeypatch):
    """Test actual headless agy execution using the system binary."""
    agy_path = shutil.which("agy") or "/home/sooriya/.local/bin/agy"
    if not Path(agy_path).exists():
        pytest.skip(f"agy binary not found at {agy_path}")

    # Configure runner to use real agy binary instead of mock
    monkeypatch.setattr(settings, "AGY_BIN_PATH", agy_path)
    monkeypatch.setattr(settings, "AGY_MOCK", False)
    monkeypatch.setattr(settings, "JOB_TIMEOUT_SECONDS", 60)

    headers = {"Idempotency-Key": "live-headless-agy-001"}
    payload = {"script": "Test harmless headless task for video engine verification."}
    res = await client.post("/api/v1/broll/jobs", json=payload, headers=headers)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    # Poll status until terminal state (real LLM turn can take 20-40s)
    data = None
    for _ in range(90):
        res_get = await client.get(f"/api/v1/jobs/{job_id}")
        assert res_get.status_code == 200
        data = res_get.json()
        if data["status"] in ["succeeded", "failed"]:
            break
        await asyncio.sleep(1.0)

    assert data is not None
    assert data["status"] == "succeeded", f"Job failed: {data.get('error')}"
    assert data["progress"] == 100
    assert data["stage"] == "completed"

    # Verify stdout and stderr log files were generated
    logs_dir = isolated_storage["jobs_dir"] / job_id / "logs"
    assert (logs_dir / "stdout.log").exists()
    assert (logs_dir / "stderr.log").exists()

    # Verify artifacts were generated
    artifacts_dir = isolated_storage["jobs_dir"] / job_id / "artifacts"
    assert (artifacts_dir / "timeline.json").exists()
    assert (artifacts_dir / "manifest.json").exists()
    assert (artifacts_dir / "captions.srt").exists()
