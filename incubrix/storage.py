"""Persistent file-backed storage and idempotency management for IncuBrix Video Engine."""

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid

from incubrix.config import settings
from incubrix.models import IncuBrixAPIException, JobRecord


def compute_payload_hash(payload: Union[Dict[str, Any], bytes, str]) -> str:
    """Compute a deterministic SHA-256 hash for JSON payloads, strings, or bytes."""
    if isinstance(payload, dict):
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    elif isinstance(payload, str):
        serialized = payload.encode("utf-8")
    elif isinstance(payload, bytes):
        serialized = payload
    else:
        serialized = str(payload).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


class IdempotencyManager:
    """Thread-safe, file-backed idempotency registry.

    Maps `Idempotency-Key` -> (job_id, payload_hash) persisted in data/idempotency.json.
    """

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self._lock = threading.RLock()
        self._async_lock = asyncio.Lock()
        self._ensure_file()

    def _ensure_file(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            with self._lock:
                if not self.file_path.exists():
                    self._atomic_write({})

    def _read_records(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            if not self.file_path.exists():
                return {}
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}

    def _atomic_write(self, data: Dict[str, Any]) -> None:
        temp_path = self.file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, self.file_path)

    def check_and_register(
        self, idempotency_key: Optional[str], payload_hash: str, job_id: str
    ) -> Tuple[bool, str]:
        """Check idempotency key against registered records.

        Returns:
            (is_existing: bool, job_id: str)

        Raises:
            IncuBrixAPIException: 400 MISSING_IDEMPOTENCY_KEY if key is None or empty.
            IncuBrixAPIException: 409 IDEMPOTENCY_KEY_CONFLICT if key exists with different payload hash.
        """
        if not idempotency_key or not idempotency_key.strip():
            if settings.REQUIRE_IDEMPOTENCY_KEY:
                raise IncuBrixAPIException(
                    status_code=400,
                    code="MISSING_IDEMPOTENCY_KEY",
                    message="Missing required Idempotency-Key header.",
                    details={"header": "Idempotency-Key"},
                )
            key = str(uuid.uuid7()) if hasattr(uuid, "uuid7") else str(uuid.uuid4())
        else:
            key = idempotency_key.strip()

        with self._lock:
            records = self._read_records()
            if key in records:
                entry = records[key]
                stored_hash = entry.get("payload_hash")
                if stored_hash == payload_hash:
                    # Same key + same payload => return existing job_id
                    return True, entry.get("job_id")
                else:
                    # Same key + different payload => raise 409 Conflict
                    raise IncuBrixAPIException(
                        status_code=409,
                        code="IDEMPOTENCY_KEY_CONFLICT",
                        message="Idempotency key has already been used with a different request payload.",
                        details={
                            "idempotency_key": key,
                            "existing_job_id": entry.get("job_id"),
                        },
                    )

            # Not found: register new key mapping
            records[key] = {
                "job_id": job_id,
                "payload_hash": payload_hash,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            self._atomic_write(records)
            return False, job_id

    async def check_and_register_async(
        self, idempotency_key: Optional[str], payload_hash: str, job_id: str
    ) -> Tuple[bool, str]:
        async with self._async_lock:
            return self.check_and_register(idempotency_key, payload_hash, job_id)

    def get_job_id(self, idempotency_key: str) -> Optional[str]:
        records = self._read_records()
        entry = records.get(idempotency_key)
        return entry.get("job_id") if entry else None


class JobStore:
    """Thread-safe, asyncio-compatible file-backed job store.

    Stores each job's metadata as JSON under data/jobs/{job_id}/job.json.
    """

    def __init__(self, jobs_dir: Path, idempotency_manager: IdempotencyManager):
        self.jobs_dir = jobs_dir
        self.idempotency_manager = idempotency_manager
        self._lock = threading.RLock()
        self._async_lock = asyncio.Lock()
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def _job_dir(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def _job_path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "job.json"

    def _atomic_write_job(self, job_path: Path, job_data: Dict[str, Any]) -> None:
        job_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = job_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(job_data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, job_path)

    # ==========================================================================
    # Synchronous Operations
    # ==========================================================================

    def save_job_sync(self, job: JobRecord) -> JobRecord:
        """Persist or overwrite a job record to disk."""
        with self._lock:
            path = self._job_path(job.job_id)
            self._atomic_write_job(path, job.model_dump())
            return job

    def get_job_sync(self, job_id: str) -> Optional[JobRecord]:
        """Load a job record from disk by job_id."""
        with self._lock:
            path = self._job_path(job_id)
            if not path.exists():
                return None
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return JobRecord.model_validate(data)
            except Exception:
                return None

    def update_job_sync(self, job_id: str, updates: Dict[str, Any]) -> JobRecord:
        """Update fields of an existing job record."""
        with self._lock:
            job = self.get_job_sync(job_id)
            if not job:
                raise IncuBrixAPIException(
                    status_code=404,
                    code="JOB_NOT_FOUND",
                    message=f"Job '{job_id}' not found.",
                    details={"job_id": job_id},
                )
            current_data = job.model_dump()
            current_data.update(updates)
            updated_job = JobRecord.model_validate(current_data)
            self.save_job_sync(updated_job)
            return updated_job

    def list_jobs_sync(self, limit: int = 50, offset: int = 0) -> List[JobRecord]:
        """List jobs ordered by creation date descending."""
        with self._lock:
            jobs: List[JobRecord] = []
            if not self.jobs_dir.exists():
                return []
            for child in self.jobs_dir.iterdir():
                if child.is_dir():
                    job_file = child / "job.json"
                    if job_file.exists():
                        try:
                            with open(job_file, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            jobs.append(JobRecord.model_validate(data))
                        except Exception:
                            continue
            # Sort descending by created_at
            jobs.sort(key=lambda j: j.created_at, reverse=True)
            return jobs[offset : offset + limit]

    def job_exists(self, job_id: str) -> bool:
        return self._job_path(job_id).exists()

    # ==========================================================================
    # Asynchronous Operations
    # ==========================================================================

    async def save_job(self, job: JobRecord) -> JobRecord:
        async with self._async_lock:
            return self.save_job_sync(job)

    async def get_job(self, job_id: str) -> Optional[JobRecord]:
        async with self._async_lock:
            return self.get_job_sync(job_id)

    async def update_job(self, job_id: str, updates: Dict[str, Any]) -> JobRecord:
        async with self._async_lock:
            return self.update_job_sync(job_id, updates)

    async def list_jobs(self, limit: int = 50, offset: int = 0) -> List[JobRecord]:
        async with self._async_lock:
            return self.list_jobs_sync(limit=limit, offset=offset)


_job_store: Optional[JobStore] = None


def get_job_store() -> JobStore:
    global _job_store
    if _job_store is None:
        idempotency_file = settings.JOBS_DIR.parent / "idempotency.json"
        idempotency_mgr = IdempotencyManager(idempotency_file)
        _job_store = JobStore(settings.JOBS_DIR, idempotency_mgr)
    return _job_store


# Module-level job_store instance
job_store = get_job_store()
