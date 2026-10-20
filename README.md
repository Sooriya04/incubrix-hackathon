# IncuBrix Script-to-B-Roll Video Engine

Local FastAPI service that turns a script, scene list, or audio URL into MP4 video, captions, timeline metadata, and a rights manifest.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn incubrix.api:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

## Test

```bash
pytest -q
```

The Remotion integration test needs a writable temporary webpack cache and the local Node dependencies. Other tests use the mock pipeline and do not need API keys.

## Configuration

Copy `.env.example` to `.env` and set only the credentials needed for live providers. `AGY_MOCK=true` enables the deterministic local path.

## API

The main endpoint is `POST /api/v1/broll/jobs`. It accepts exactly one of `script`, `scenes`, or `audio_url`, returns `202` with a job ID, and exposes progress at `GET /api/v1/jobs/{job_id}`. See `openapi.yaml` and `API_CONTRACT.md`.

## Known limitations

- Stock footage falls back to internal developer plates when providers are unavailable.
- The live Antigravity CLI requires an authenticated local session and may be slower than the configured generation timeout.
- This repository is intentionally prepared for local execution; containerization is not included.
