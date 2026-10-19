"""Test failure conditions: crashes, timeouts, exit codes, and secret redaction."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from incubrix.config import settings
from incubrix.models import JobRecord
from incubrix.runner import redact_secrets, runner
from incubrix.storage import job_store


def test_secret_redaction():
    """Verify secrets are redacted from logs and errors."""
    raw_text = "Failed with api_key: 'sk-proj-998877665544332211' and token=secret_abcdef123456"
    cleaned = redact_secrets(raw_text)
    assert "sk-proj-998877665544332211" not in cleaned
    assert "secret_abcdef123456" not in cleaned
    assert "***REDACTED***" in cleaned


@pytest.mark.asyncio
async def test_job_failure_on_process_crash(client: httpx.AsyncClient, monkeypatch):
    """Simulated crash/non-zero exit code records failure status and error details."""
    headers = {"Idempotency-Key": "fail-crash-001"}
    payload = {"script": "This script will trigger simulated process failure."}

    # Mock runner._run_mock_pipeline to simulate a crash
    async def mock_crashing_pipeline(job, artifacts_dir, stdout_log_path, stderr_log_path):
        err = RuntimeError("FFmpeg crashed with exit code 137: Out of Memory")
        setattr(err, "exit_code", 137)
        raise err

    monkeypatch.setattr(runner, "_run_mock_pipeline", mock_crashing_pipeline)

    res = await client.post("/api/v1/broll/jobs", json=payload, headers=headers)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    # Poll status
    for _ in range(30):
        res_get = await client.get(f"/api/v1/jobs/{job_id}")
        data = res_get.json()
        if data["status"] == "failed":
            break
        await asyncio.sleep(0.1)

    assert data["status"] == "failed"
    assert data["stage"] == "failed"
    assert data["failed_at"] is not None
    assert data["error"] is not None
    assert data["error"]["code"] == "RENDER_PIPELINE_FAILED"
    assert "FFmpeg crashed" in data["error"]["message"]
    assert data["error"]["details"]["exit_code"] == 137
    assert data["artifacts"] is None


@pytest.mark.asyncio
async def test_job_failure_on_timeout(client: httpx.AsyncClient, monkeypatch):
    """Simulated process timeout records TIMEOUT_EXCEEDED error."""
    headers = {"Idempotency-Key": "fail-timeout-002"}
    payload = {"script": "This script will trigger simulated timeout."}

    async def mock_timeout_pipeline(job, artifacts_dir, stdout_log_path, stderr_log_path):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(runner, "_run_mock_pipeline", mock_timeout_pipeline)

    res = await client.post("/api/v1/broll/jobs", json=payload, headers=headers)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    for _ in range(30):
        res_get = await client.get(f"/api/v1/jobs/{job_id}")
        data = res_get.json()
        if data["status"] == "failed":
            break
        await asyncio.sleep(0.1)

    assert data["status"] == "failed"
    assert data["stage"] == "failed"
    assert data["error"]["code"] == "TIMEOUT_EXCEEDED"
    assert "timed out" in data["error"]["message"]
