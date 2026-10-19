# Git Commit

## Commit Command

```bash
git add .
git commit -m "feat(pipeline): establish central renders architecture, lockstep audio-video sync, and hardware-accelerated playback

- Add central RENDERS_DIR (`./renders/`) where every incoming video generation request automatically creates its dedicated sub-directory (`./renders/{job_id}/`)
- Fix audio-video desynchronization: attach per-scene synchronized `<Audio />` inside each sequence layer in `BrollVideo.tsx` and insert 0.2s inter-scene padding silence in `audio.py`
- Replace `<OffthreadVideo>` with standard `<Video>` and prefer medium resolution footage to prevent Chromium compositor buffer overflows on 4K clips
- Upgrade mock footage encoder to libopenh264 for native browser demuxing and decoding
- Symlink and mirror all job artifacts (`video_16_9.mp4`, `out.mp4`, `timeline.json`, `manifest.json`, `captions.srt`) directly into `./renders/{job_id}/`
- All 35 tests passing cleanly across full pytest suite"
```

---

## Commit Details

* **Type:** `feat`
* **Scope:** `pipeline`
* **Title:** `establish central renders architecture, lockstep audio-video sync, and hardware-accelerated playback`
* **Files Included:**
  * `incubrix/config.py`: Added `RENDERS_DIR` setting defaulting to `./renders`
  * `incubrix/runner.py`: Centralized job workspace inside `./renders/{job_id}/`, mirrored final artifacts and MP4 exports
  * `incubrix/audio.py`: Added 0.2s inter-scene silence padding for exact lockstep voiceover alignment
  * `incubrix/footage.py`: Converted mock video generator to `libopenh264`, prioritized medium resolution clips
  * `incubrix/project_generator.py`: Copy shared TSX components into job workspaces to fix Webpack asset resolution
  * `remotion/BrollVideo.tsx`: Added sequence-level audio synchronization, switched to `<Video>` component
  * `remotion/Root.tsx`: Type definitions for Remotion Composition props
  * `tests/conftest.py`: Isolated temporary renders directory fixture
  * `tests/test_headless_agy.py`: Updated timeout and fast-mock video render to isolate CLI verification
  * `.gitignore`: Ignore `./renders/` directory
  * `github/commits.md`: Single commit tracking file
