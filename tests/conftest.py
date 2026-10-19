"""Pytest fixtures for IncuBrix test suite."""

import asyncio
from pathlib import Path
import shutil
import tempfile
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio

from incubrix.api import app
from incubrix.config import settings
from incubrix.storage import IdempotencyManager, JobStore, job_store


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch):
    """Isolate storage and jobs directory for each test run."""
    temp_dir = Path(tempfile.mkdtemp(prefix="incubrix_test_"))
    test_jobs_dir = temp_dir / "jobs"
    test_storage_dir = temp_dir / "storage"
    test_idemp_file = temp_dir / "idempotency.json"

    test_jobs_dir.mkdir(parents=True, exist_ok=True)
    test_storage_dir.mkdir(parents=True, exist_ok=True)
    test_renders_dir = temp_dir / "renders"
    test_renders_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "JOBS_DIR", test_jobs_dir)
    monkeypatch.setattr(settings, "STORAGE_DIR", test_storage_dir)
    monkeypatch.setattr(settings, "RENDERS_DIR", test_renders_dir)
    monkeypatch.setattr(settings, "AGY_MOCK", True)  # Default to fast mock harness

    # Re-initialize job_store with test paths
    test_idemp_manager = IdempotencyManager(file_path=test_idemp_file)
    test_job_store = JobStore(jobs_dir=test_jobs_dir, idempotency_manager=test_idemp_manager)

    monkeypatch.setattr("incubrix.storage.job_store", test_job_store)
    monkeypatch.setattr("incubrix.api.job_store", test_job_store)
    monkeypatch.setattr("incubrix.runner.job_store", test_job_store)

    yield {
        "temp_dir": temp_dir,
        "jobs_dir": test_jobs_dir,
        "storage_dir": test_storage_dir,
        "idemp_file": test_idemp_file,
        "job_store": test_job_store,
    }

    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP test client bound to FastAPI application."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
