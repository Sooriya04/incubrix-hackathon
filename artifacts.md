# IncuBrix Script-to-B-Roll Video Engine  Phase 2 Task 2.1 Progress Log

**Generated Date:** 2026-10-19  
**Status:** Completed & Fully Verified  
**Task:** Phase 2, Task 2.1  Asynchronous `agy` Headless Job Launcher

---

## 1. Executive Summary & Goals

The objective of Task 2.1 was to implement the asynchronous headless job launcher for the IncuBrix video generation engine, adhering strictly to `API_CONTRACT.md` and `openapi.yaml`.

### Acceptance Criteria Verification Matrix
| # | Acceptance Criterion | Implementation Details | Test Coverage | Result |
|---|---|---|---|---|
| 1 | `POST /api/v1/broll/jobs` returns `202 Accepted` immediately | Validates input mode and idempotency, creates unique `job_<uuid>`, persists initial `queued` state, and returns HTTP 202 with `Location` and `X-Correlation-Id` without blocking. | `tests/test_lifecycle.py::test_job_submission_and_lifecycle` | **PASS** |
| 2 | Agent runs independently in headless mode | Spawns `agy -p "<prompt>" --dangerously-skip-permissions` as a separate detached subprocess via `asyncio.create_subprocess_exec` inside an isolated job workspace. | `tests/test_headless_agy.py::test_live_headless_agy_execution` | **PASS** |
| 3 | Status endpoint accurately reports progress and completion | `GET /api/v1/jobs/{job_id}` and alias `GET /api/v1/broll/jobs/{job_id}` track state transitions (`queued` -> `running` -> `succeeded`), stages (`transcribing`/`segmenting`/`completed`), timestamps, durations, and artifact links. | `tests/test_lifecycle.py::test_job_submission_and_lifecycle` | **PASS** |
| 4 | Failures recorded and returned clearly in contract error format | Handles process crashes (captures exit code), timeouts (`TIMEOUT_EXCEEDED`), schema violations (`EMPTY_SCRIPT`, `SCRIPT_TOO_LONG`, `UNSUPPORTED_ASPECT_RATIO`, `INVALID_SCENE_SEQUENCE`, `INVALID_INPUT_MODE`), and duplicate conflicts (`IDEMPOTENCY_KEY_CONFLICT`). Redacts credentials. | `tests/test_runner_failures.py`, `tests/test_validation.py`, `tests/test_idempotency.py` | **PASS** |
| 5 | Tests pass 100% without requiring paid API credentials | Deterministic mock runner provides simulated progress and dummy contract deliverables (`timeline.json`, `manifest.json`, `captions.srt`, `video_*.mp4`) in 0.8s offline. Live test verifies system `agy` binary. | `tests/` (18 passing tests) | **PASS** |

---

## 2. Architecture & File Structure

```
/media/workspace/incubrix-hackathon/
 API_CONTRACT.md              # Canonical contract specification
 openapi.yaml                 # OpenAPI 3.1 specification
 pyproject.toml               # Package configuration & pytest settings
 artifacts.md                 # Complete task implementation log
 incubrix/
    __init__.py              # Package init
    config.py                # Environment-driven settings (pydantic-settings)
    models.py                # Strict Pydantic models matching API contract & error catalog
    storage.py               # Atomic file-backed persistent job store & idempotency registry
    runner.py                # Headless `agy` subprocess supervisor & mock harness
    api.py                   # FastAPI REST API endpoints & correlation middleware
 tests/
    __init__.py
    conftest.py              # Isolated test fixtures & async HTTP test client
    test_validation.py       # Contract schema & input validation tests
    test_idempotency.py      # Safe retry & conflict detection tests
    test_lifecycle.py        # Asynchronous job state transitions & persistence tests
    test_runner_failures.py  # Process crash, timeout, and secret redaction tests
    test_headless_agy.py     # Live headless `agy` CLI integration test
 data/                        # Persistent runtime storage (survives restarts)
     idempotency.json         # Idempotency key -> (job_id, payload_hash) registry
     jobs/
         {job_id}/
             job.json         # Persisted state machine record
             input.json       # Validated request input
             logs/
                stdout.log   # Raw headless stdout
                stderr.log   # Raw headless stderr
             workspace/       # Isolated sandbox workspace
             artifacts/       # Deliverables (video_*.mp4, captions.srt, timeline.json, manifest.json)
```

---

## 3. Test Suite Execution Summary

Using `.venv/bin/pytest -v tests/`:

```
tests/test_headless_agy.py::test_live_headless_agy_execution PASSED      [  5%]
tests/test_idempotency.py::test_idempotent_retry_returns_same_job PASSED [ 11%]
tests/test_idempotency.py::test_idempotent_conflict_on_different_payload PASSED [ 16%]
tests/test_lifecycle.py::test_job_submission_and_lifecycle PASSED        [ 22%]
tests/test_lifecycle.py::test_job_persistence_across_restart PASSED      [ 27%]
tests/test_runner_failures.py::test_secret_redaction PASSED              [ 33%]
tests/test_runner_failures.py::test_job_failure_on_process_crash PASSED  [ 38%]
tests/test_runner_failures.py::test_job_failure_on_timeout PASSED        [ 44%]
tests/test_validation.py::test_health_and_ready PASSED                   [ 50%]
tests/test_validation.py::test_missing_idempotency_key PASSED            [ 55%]
tests/test_validation.py::test_invalid_json_body PASSED                  [ 61%]
tests/test_validation.py::test_strict_xor_primary_input_mode_none PASSED [ 66%]
tests/test_validation.py::test_strict_xor_primary_input_mode_multiple PASSED [ 72%]
tests/test_validation.py::test_empty_script_validation PASSED            [ 77%]
tests/test_validation.py::test_script_too_long PASSED                    [ 83%]
tests/test_validation.py::test_unsupported_aspect_ratio PASSED           [ 88%]
tests/test_validation.py::test_scene_sequence_validation PASSED          [ 94%]
tests/test_validation.py::test_job_not_found PASSED                      [100%]

============================= 18 passed in 22.85s ==============================
```

Offline test execution time (mock harness): **0.80 seconds** across 17 tests.
Live headless `agy` integration test time: **19.08 seconds**.
Code warnings: **0 warnings, 0 deprecations**.
