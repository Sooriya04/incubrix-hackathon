# IncuBrix Studio — Technical Documentation

## What It Is

IncuBrix is an AI-powered B-Roll video engine that converts a topic prompt or narration script into a fully rendered MP4 video with voiceover, captions, and stock footage. It runs entirely locally with a browser UI at `http://localhost:8000`.

---

## Architecture

```
Browser (index.html)
      |
FastAPI (incubrix/api.py) on port 8000
      |
      |-- /api/v1/auth/*         Google OAuth (Antigravity client credentials)
      |-- /api/v1/script/generate  AI script generation via agy CLI or fallback
      |-- /api/v1/jobs/*          Video job CRUD (SQLite backed)
      |
JobRunner (incubrix/runner.py)
      |
      |-- ScriptCalibrator        Trim/expand script to match exact duration
      |-- AudioPipeline           edge-tts TTS + espeak-ng fallback + ffmpeg concat
      |-- RemotionRenderer        npx remotion render (concurrency=1, scale=0.5)
      |-- FallbackRenderer        ffmpeg dark-plate + audio if Remotion fails
      |
SQLite (data/incubrix.db)        Job history, idempotency keys
```

---

## Auth Flow

The app uses the **Antigravity public OAuth client** (same credentials as `agy` CLI) to authenticate via Google.

### Auto-Login (preferred)
If the host machine already has an active `agy` session (`~/.gemini/antigravity-cli/antigravity-oauth-token`), the app **auto-connects on page load** — no click needed.

### Google OAuth (manual)
1. User clicks **Direct Sign in with Google Account** — redirects in same tab to Google consent screen
2. Google redirects back to `/api/v1/auth/callback?code=...`
3. Server exchanges code for tokens using Antigravity client credentials
4. Token saved to `~/.gemini/antigravity-cli/antigravity-oauth-token`
5. Page redirects to `/?auth_success=true&email=...&token=...`
6. JS reads URL params, sets `currentAuth` in localStorage, shows Studio

**Key fix (commit 4d735d8):** `redirect_uri` now uses the `Host` request header instead of `request.base_url`. This prevents the `0.0.0.0` vs `localhost` mismatch that caused Google to reject the token exchange and keep users on the auth page.

---

## Duration Control

Users enter a number + unit (seconds or minutes) in the Studio:

```
[ 90 ] [ sec | min ]
```

The value is converted to seconds: `val * (unit === 'min' ? 60 : 1)`.

Metrics (word count, scene count, formatted duration) update live as the user types.

### Script Calibration

When a video is generated, `calibrate_script_to_duration(text, duration_sec)` is called in `incubrix/script_generator.py`:

- Target words = `(duration_sec / 60) * 140` (140 wpm speech rate)
- Splits script into sentences
- Greedily selects sentences up to `target_words * 1.15` tolerance
- Result: video speech always fits the requested duration, regardless of input script length

---

## Video Rendering

Rendering is done via Remotion with conservative resource settings for low-RAM machines:

```
npx remotion render index.ts <composition> output.mp4
  --concurrency 1     (single worker, ~1.5GB peak RAM)
  --gl swiftshader    (software GPU, no hardware requirement)
  --scale 0.5         (540p output, fast encode)
```

If Remotion fails or times out, the fallback assembles an MP4 using ffmpeg: dark background + voiceover audio. The job never hard-fails for the user — they always get a video file.

---

## Job History (SQLite)

All jobs are stored in `data/incubrix.db` with two tables:

- `jobs` — job_id, status, stage, progress, request payload, friendly title, timestamps
- `idempotency` — deduplication keys with TTL

The History sidebar shows all past jobs. You can rename job titles inline (click the rename button next to any item).

---

## Running Locally

```bash
# Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Start server
uvicorn incubrix.api:app --host 0.0.0.0 --port 8000

# Open browser
open http://localhost:8000
```

---

## Future Plans

### Short-term (next sprint)

| Item | Priority | Notes |
|------|----------|-------|
| Real stock footage via Pexels/Pixabay API | High | Currently uses placeholder clips. Needs `PIXABAY_API_KEY` in `.env` |
| Progress streaming via SSE | High | Currently polls every 2s. Replace with `/api/v1/jobs/{id}/stream` |
| Per-scene visual hints → footage search query | High | `visual_hint` field exists in scene metadata, not used for search yet |
| Mobile-responsive UI | Medium | Layout breaks below 600px |
| Multiple language TTS voices | Medium | edge-tts supports 300+ voices, expose more in UI |

### Medium-term

| Item | Notes |
|------|-------|
| Chunk-based rendering | Split long videos (>3min) into per-scene MP4s, concat at the end to avoid RAM spike |
| Background music layer | Add ambient music track with ducking under voiceover |
| Caption style themes | Currently single monospaced style. Add word-highlight, bottom-third, etc. |
| Multi-user auth | Replace localStorage session with server-side sessions and per-user job isolation |
| Cloud storage output | Upload finished MP4s to GCS/S3, return presigned URL instead of serving from disk |

### Long-term

| Item | Notes |
|------|-------|
| Generative B-roll | Replace stock footage with AI-generated video clips (Veo 2, Kling, etc.) |
| Custom brand templates | Let users upload brand fonts, colors, logo — inject into Remotion composition |
| Batch generation | Accept a list of topics, generate multiple videos in parallel (with queue) |
| Webhook callbacks | POST to user endpoint when job completes (for headless/CI use) |

---

## Known Limits

- **RAM:** Rendering peaks at ~2GB per job. Do not run more than 1 concurrent real render on a 7GB machine.
- **Timeout:** Jobs timeout after 300s (configurable via `JOB_TIMEOUT_SECONDS` env var). Long videos (5+ min) may hit this on slow machines.
- **Stock footage:** Without a Pixabay/Pexels API key, video uses placeholder dark-plate backgrounds.
- **Google OAuth:** Requires the machine to have internet access during the token exchange step.
