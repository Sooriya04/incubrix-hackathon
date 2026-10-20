# Git Commit

## Commit Command

```bash
git add .
git commit -m "feat(studio): add SQLite history sidebar, duration selector, AI script research, and lightweight rendering safeguards

- Implement SQLite database backend (data/incubrix.db) with jobs table and full history persistence
- Add History Sidebar in static/index.html with friendly title renaming, status badges, and 1-click video loading
- Add Target Duration selector (30s, 1:00, 1:30, 2:00, 3:00, 5:00 min) with live word-count and scene benchmarks
- Add AI topic research & script generation engine (incubrix/script_generator.py) using Antigravity CLI (gemini-3.8-flash-high)
- Implement CPU/RAM rendering safeguards (concurrency 2, swiftshader, 720p scale) and graceful preview fallback
- Remove robotic 'Scene 1' visual badges and voiceover text prefixes
- Enhance speech synthesis reliability with 3-retry backoff and local espeak-ng fallback
- Add video-script-researcher skill instruction file in .agents/skills/ and skills/
- Add full test suite in tests/test_history_and_script.py (all tests passing)"
```

---

## Commit Details

* **Type:** `feat`
* **Scope:** `studio`
* **Title:** `add SQLite history sidebar, duration selector, AI script research, and lightweight rendering safeguards`
* **Files Included:**
  * `incubrix/storage.py`: SQLite `data/incubrix.db` integration, job listing, friendly title renaming, atomic disk sync
  * `incubrix/script_generator.py`: AI topic research and duration calibration engine using Antigravity CLI
  * `incubrix/api.py`: History endpoints (`/api/v1/jobs`, `/api/v1/jobs/{id}/title`), script research endpoint (`/api/v1/script/generate`), and auto-expansion
  * `incubrix/runner.py`: Lightweight CPU/RAM safeguards (`--concurrency 2`, `--gl swiftshader`, `--scale 0.67`) and graceful preview fallback
  * `incubrix/audio.py`: Reliable speech synthesis (3 retries + `espeak-ng` fallback) and 'Scene 1' prefix stripper
  * `remotion/BrollVideo.tsx`: Removed `[SCENE 01 · ...]` debug badge
  * `static/index.html`: SQLite History Sidebar, Duration dropdown, live metrics bar, AI script generator button, and inline title renamer
  * `.agents/skills/video-script-researcher/SKILL.md` & `skills/video-script-researcher/SKILL.md`: Comprehensive skill instructions
  * `tests/test_history_and_script.py`: Unit tests for duration parsing, voiceover cleaning, SQLite storage, and API endpoints
  * `github/commits.md`: Single commit tracking file
