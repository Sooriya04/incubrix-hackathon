# Git Commit

## Commit Command

```bash
git add .
git commit -m "feat(engine): implement Phase 2 Task 2.1 asynchronous headless agy job launcher

- Add FastAPI endpoints (POST /api/v1/broll/jobs, GET /api/v1/jobs/{job_id}, health checks)
- Implement strict API contract validation (XOR input mode, script bounds, aspect ratios)
- Support automatic time-ordered UUIDv7 idempotency keys and conflict detection (409)
- Implement headless agy background process supervisor with stdout/stderr capture and secret redaction
- Add persistent atomic file-backed job store surviving worker/container restarts
- Add comprehensive pytest suite with 18 unit/integration tests passing (mock harness + live agy)
- Configure pyproject.toml and virtual environment with uv"
```

---

## Commit Details

* **Type:** `feat`
* **Scope:** `engine`
* **Title:** `implement Phase 2 Task 2.1 asynchronous headless agy job launcher`
* **Files Included:**
  * `incubrix/config.py`: Environment configuration and directory bootstrap
  * `incubrix/models.py`: Pydantic request/response models and contract validation
  * `incubrix/storage.py`: Atomic persistent job store and UUIDv7 idempotency manager
  * `incubrix/runner.py`: Headless `agy` process supervisor and offline mock harness
  * `incubrix/api.py`: FastAPI application, endpoints, and correlation ID middleware
  * `tests/`: 18 passing automated tests (`test_validation.py`, `test_idempotency.py`, `test_lifecycle.py`, `test_runner_failures.py`, `test_headless_agy.py`)
  * `pyproject.toml`, `.gitignore`: Build and package management with `uv`
  * `phase.md`, `artifacts.md`, `github/commits.md`: Task documentation and progress logs
