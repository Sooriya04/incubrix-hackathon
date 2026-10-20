# Pre-Docker Readiness Report

## Verified

- FastAPI job API with queued/running/succeeded/failed states.
- Idempotency handling and structured error envelopes.
- SQLite-backed job history and persistent artifacts.
- Mock audio, footage, and render paths for tests without API keys.
- Remotion project generation with per-job captions and configuration.
- Health and readiness endpoints.

## Partial

- Real provider output depends on local credentials and network access.
- A stopped worker can leave persisted records behind; startup recovery now marks orphaned jobs as failed with `WORKER_STOPPED`.
- The full Remotion integration test requires a writable webpack cache; the current restricted environment reports `EROFS` while Remotion clears that cache.

## Not claimed

- No Docker or compose packaging is included.
- No measured 10-input relevance benchmark is claimed yet.
- No S3/MinIO storage adapter or batch runner is included yet.
