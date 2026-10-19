# Git Commit

## Commit Command

```bash
git add .
git commit -m "feat(remotion): connect automated multi-ratio remotion rendering into background job lifecycle

- Integrate render_remotion_ratio into JobRunner for all requested aspect ratios
- Save rendered videos directly to artifacts/video_{ratio}.mp4
- Add ffprobe playback and duration verification to prevent false-positive completions
- Add tests/test_remotion_rendering.py covering mock multi-ratio, failure handling, and real 1080p Remotion render
- Verify 31 automated tests passing and live API artifact retrieval"
```

---

## Commit Details

* **Type:** `feat`
* **Scope:** `remotion`
* **Title:** `connect automated multi-ratio remotion rendering into background job lifecycle`
* **Files Included:**
  * `incubrix/runner.py`: Automatic Remotion render integration, path resolution, and ffprobe validation
  * `tests/test_remotion_rendering.py`: Test suite for automated multi-ratio rendering, error cases, and real Remotion export
  * `phase.md`: Documented Phase 3 Task 3.2 completion and test verification
  * `github/commits.md`: Single commit tracking file
