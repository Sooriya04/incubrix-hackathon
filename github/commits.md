# Git Commit

## Commit Command

```bash
git add .
git commit -m "feat(footage): implement Pixabay B-roll discovery with rate-limiting, disk caching, and licensing guardrails

- Implement PixabayClient in incubrix/footage.py with two-tier disk cache (queries & videos)
- Enforce strict 1 req/sec rate-limiting to prevent 429 quota exhaustion
- Support negative constraint filtering (avoid list) against video tags
- Attach real clip licensing, attribution, and trim metadata to timeline.json and manifest.json
- Update remotion/BrollVideo.tsx OffthreadVideo to seamlessly render downloaded clips with active captions
- Add tests/test_footage.py with 35 total tests passing across entire repository"
```

---

## Commit Details

* **Type:** `feat`
* **Scope:** `footage`
* **Title:** `implement Pixabay B-roll discovery with rate-limiting, disk caching, and licensing guardrails`
* **Files Included:**
  * `incubrix/footage.py`: Pixabay API integration, two-tier cache, rate-limiting, and offline fallback
  * `incubrix/runner.py`: Pipeline integration for footage discovery, dynamic timeline.json generation
  * `incubrix/config.py`: PIXABAY_API_KEY, PEXELS_API_KEY, and CACHE_DIR configuration
  * `remotion/BrollVideo.tsx`: Video source resolution supporting staticFile and downloaded clips
  * `tests/test_footage.py`: Unit tests for query cleaning, caching, negative constraints, and offline mocks
  * `.gitignore`: Ensure .env and credentials are never tracked
  * `phase.md`: Documented Phase 2 Task 2.4 completion and test verification
  * `github/commits.md`: Single commit tracking file
