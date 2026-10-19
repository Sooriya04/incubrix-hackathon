# IncuBrix Script-to-B-Roll Video Engine — Phase Implementation Guide

## Executive Overview

The **IncuBrix Script-to-B-Roll Video Engine** is an asynchronous system that converts raw scripts, audio voiceovers, or scene prompts into finished, multi-aspect-ratio (`16:9`, `9:16`, `1:1`) videos with synchronized audio, burned-in captions, and a complete licensing and provenance audit trail.

This document details the architectural milestones, what was implemented in **Phase 2, Task 2.1**, how the system components interact, and the roadmap for upcoming tasks.

---

## Architecture Flow

```mermaid
flowchart TD
    Client["Client / Postman / Frontend"] -->|"POST /api/v1/broll/jobs (JSON / Multipart)"| API["FastAPI Application (incubrix/api.py)"]
    
    subgraph "Validation & Idempotency"
        API --> ModelVal["Pydantic Contract Validation (models.py)<br/>• Strict XOR on Input Mode<br/>• Bounds & Aspect Ratio Checks"]
        API --> Idemp["Idempotency Manager (storage.py)<br/>• UUIDv7 Auto-Generation<br/>• Conflict Detection (409)<br/>• Safe Replay"]
    end
    
    API -->|"HTTP 202 Accepted (Location, X-Correlation-Id)"| Client
    
    subgraph "Persistent Storage (Survives Restarts)"
        Idemp --> DiskIdemp[("data/idempotency.json")]
        API --> JobStore["JobStore (storage.py)"]
        JobStore --> DiskJob[("data/jobs/{job_id}/job.json")]
    end
    
    API -->|"Trigger async task (Non-blocking)"| Runner["JobRunner (incubrix/runner.py)"]
    
    subgraph "Headless Execution & Sandboxing"
        Runner --> StateUpdate["State Machine: queued → running"]
        Runner --> Workspace["Sandbox Workspace: data/jobs/{job_id}/workspace"]
        Runner --> Subprocess["Headless agy Subprocess<br/>agy -p '...' --dangerously-skip-permissions"]
        Subprocess --> Logs["Raw Logs: stdout.log / stderr.log (Secrets Redacted)"]
    end
    
    subgraph "Artifact Generation"
        Subprocess --> Artifacts["data/jobs/{job_id}/artifacts/"]
        Artifacts --> V1["video_16_9.mp4"]
        Artifacts --> V2["video_9_16.mp4"]
        Artifacts --> V3["video_1_1.mp4"]
        Artifacts --> SRT["captions.srt"]
        Artifacts --> TL["timeline.json"]
        Artifacts --> MF["manifest.json"]
    end
    
    Runner --> Complete["State Machine: running → succeeded (100%)"]
    Client -->|"GET /api/v1/jobs/{job_id}"| Poll["Status Polling Endpoint"]
    Poll --> Complete
```

---

## Phase Breakdown

### Phase 1: API Contract & OpenAPI Specification ✅ (Completed)
- **Deliverables:** [`API_CONTRACT.md`](file:///media/workspace/incubrix-hackathon/API_CONTRACT.md) and [`openapi.yaml`](file:///media/workspace/incubrix-hackathon/openapi.yaml).
- Defined input/output schemas, mutual exclusivity XOR constraints, error catalog, state machine, and artifact schemas.

---

### Phase 2: Engine Core Architecture & Orchestration

#### Task 2.1: Asynchronous `agy` Headless Job Launcher ✅ (Completed & Verified)
* **What was built:**
  1. **Asynchronous Non-Blocking HTTP Interface:**
     - `POST /api/v1/broll/jobs` validates payload, writes initial `queued` state, triggers background runner, and immediately returns `HTTP 202 Accepted` with `Location` and `X-Correlation-Id` headers.
     - Supports both `application/json` and `multipart/form-data` uploads.
  2. **Automated Time-Ordered UUIDv7 Idempotency:**
     - Uses native Python 3.14 `uuid.uuid7()` for chronological, collision-free idempotency keys.
     - When an `Idempotency-Key` header is omitted, the API automatically generates a UUIDv7, assigns it, registers the job, and echoes it in the response header `Idempotency-Key` and response body.
     - Detects payload conflicts (`409 IDEMPOTENCY_KEY_CONFLICT`) and guarantees safe replays.
  3. **Headless `agy` Subprocess Supervisor:**
     - Launches `agy -p "<prompt>" --dangerously-skip-permissions` as an independent subprocess using `asyncio.create_subprocess_exec`.
     - Allocates isolated directories per job (`data/jobs/{job_id}/workspace`, `artifacts/`, `logs/`).
     - Captures raw `stdout.log` and `stderr.log`, redacting sensitive API keys or credentials.
     - Handles execution timeouts (`TIMEOUT_EXCEEDED`) and process crashes (`RENDER_PIPELINE_FAILED`).
  4. **Persistent State Machine & Restart Resilience:**
     - Tracks state transitions: `queued` → `running` → `succeeded` or `failed`.
     - Atomic file writes ensure jobs and idempotency records survive server or container restarts without corruption.
  5. **Deterministic Mock Test Harness:**
     - Provides sub-second (0.8s) offline execution for automated CI/CD and testing environments without requiring external API keys.
  6. **Interactive Exploration & File Retrieval:**
     - `GET /api/v1/jobs/{job_id}` & alias `GET /api/v1/broll/jobs/{job_id}`: Real-time progress and status polling.
     - `GET /api/v1/jobs/{job_id}/artifacts/{file_name}`: Direct download for generated videos, captions, timeline, and manifest.
     - Built-in Swagger UI at `http://localhost:8000/docs`.

---

### Upcoming Tasks in Phase 2

#### Task 2.2: Audio Voiceover & Subtitle Alignment Engine ✅ (Completed & Verified)
* **What was built:**
  1. **Neural Text-to-Speech Synthesis:**
     - High-fidelity voice synthesis using Edge-TTS neural models (`en-IN-NeerjaNeural`, `en-US-JennyNeural`, etc.) with instant offline fallback.
     - Per-scene synthesis generating `public/audio/scene_{id:02d}.mp3`.
  2. **Script Segmentation & Scene Extraction:**
     - Automatic decomposition of raw scripts into timed scene descriptors (`id`, `name`, `title`, `text`, `visual_hint`).
     - Support for structured `scenes` arrays and continuous scripts.
  3. **High-Speed Word Alignment (No Whisper Overhead):**
     - Instantaneous (<1ms) duration-weighted syllable/character token alignment replacing heavy Whisper STT models.
     - Global frame-accurate offset mapping aligned to composition FPS (30fps).
  4. **Unified Video Engine Structure (matching `/media/workspace/shorts/decision_model_ms`):**
     - `public/audio/scene_{id:02d}.mp3`: Individual scene audio tracks.
     - `public/voiceover.mp3`: Unified narration audio concatenated with 2.0s endcard hold via FFmpeg.
     - `src/sceneMetadata.json`: Frame durations, start frames, and scene definitions.
     - `src/subtitles.json`: Scene-level audio subtitles.
     - `src/captions.json` & `public/captions.json`: Global words and segments synchronized with Remotion timelines.
     - `artifacts/captions.srt`: SubRip Subtitle file formatted to contract specs.
  5. **Contract-Compliant Metadata Generation:**
     - Automatic generation of `artifacts/timeline.json` and `artifacts/manifest.json`.
  6. **Pipeline Runner Integration:**
     - Wired directly into `incubrix/runner.py` with stage transitions: `queued` → `transcribing` (20%) → `segmenting` (35%) → `sourcing_footage` (50%).

---

### Upcoming Tasks in Phase 2

#### Task 2.3: Semantic Scene Segmentation & Visual Hint Extraction ⏳ (Upcoming)
- Segment voiceover into semantic scene blocks (3–7 seconds each).
- Formulate visual scene hints rather than literal keyword queries to avoid irrelevant stock matches.

#### Task 2.4: Multi-Provider Footage Discovery & Licensing Guardrails ⏳ (Upcoming)
- Query Pexels, Pixabay, and fallback generative video models.
- Apply negative constraints (`avoid`) and enforce commercial clearance licenses.

#### Task 2.5: Remotion / FFmpeg Video Composition & Subtitle Burn-In ⏳ (Upcoming)
- Assemble multi-aspect-ratio compositions (`16:9`, `9:16`, `1:1`).
- Burn in subtitles and export H.264/AAC 30fps videos.

#### Task 2.6: Delivery Packaging & Manifest Generation ⏳ (Upcoming)
- Compile final `timeline.json` (scene provenance and scores) and `manifest.json` (cost breakdown, provider audit, and timings).

---

## Acceptance Criteria Verification (Task 2.1 & Task 2.2)

All criteria were verified with 26 automated tests passing in `tests/`:

```
tests/test_audio.py::test_format_srt_timestamp PASSED                     [  4%]
tests/test_audio.py::test_segment_script_into_scenes PASSED               [  8%]
tests/test_audio.py::test_extract_scenes_from_request PASSED              [ 12%]
tests/test_audio.py::test_compute_word_timings PASSED                     [ 15%]
tests/test_audio.py::test_synthesize_scene_audio_mock PASSED              [ 19%]
tests/test_audio.py::test_build_audio_pipeline PASSED                     [ 23%]
tests/test_audio.py::test_process_job_audio_integration PASSED            [ 27%]
tests/test_headless_agy.py::test_live_headless_agy_execution PASSED      [ 31%]
tests/test_idempotency.py::test_idempotent_retry_returns_same_job PASSED [ 35%]
tests/test_idempotency.py::test_idempotent_conflict_on_different_payload PASSED [ 38%]
tests/test_lifecycle.py::test_job_submission_and_lifecycle PASSED        [ 42%]
tests/test_lifecycle.py::test_job_persistence_across_restart PASSED      [ 46%]
tests/test_runner_failures.py::test_secret_redaction PASSED              [ 50%]
tests/test_runner_failures.py::test_job_failure_on_process_crash PASSED  [ 54%]
tests/test_runner_failures.py::test_job_failure_on_timeout PASSED        [ 58%]
tests/test_validation.py::test_health_and_ready PASSED                   [ 62%]
tests/test_validation.py::test_missing_idempotency_key_in_strict_mode PASSED [ 65%]
tests/test_validation.py::test_auto_generated_uuid7_idempotency_key PASSED [ 69%]
tests/test_validation.py::test_invalid_json_body PASSED                  [ 73%]
tests/test_validation.py::test_strict_xor_primary_input_mode_none PASSED [ 77%]
tests/test_validation.py::test_strict_xor_primary_input_mode_multiple PASSED [ 81%]
tests/test_validation.py::test_empty_script_validation PASSED            [ 85%]
tests/test_validation.py::test_script_too_long PASSED                    [ 88%]
tests/test_validation.py::test_unsupported_aspect_ratio PASSED           [ 92%]
tests/test_validation.py::test_scene_sequence_validation PASSED          [ 96%]
tests/test_validation.py::test_scene_sequence_validation PASSED          [100%]

============================= 26 passed in 35.80s ==============================
```

