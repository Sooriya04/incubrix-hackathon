# Git Commit History & Release Notes

## Commit: Fix Video Codec, Artifact Serving, and Remotion Assets

### Commit Message

```bash
fix(engine): switch to H.264 video codec, resolve artifact paths, and fix missing footage fallbacks

- Switch FFmpeg video encoding across runner and footage modules from mpeg4 to libopenh264 (avc1) with yuv420p for full browser HTML5 video playback
- Transcode legacy mpeg4 video files to standard H.264 to fix black screen in frontend player and downloaded files
- Add candidate path resolution in get_job_artifact supporting both JOBS_DIR and RENDERS_DIR alongside HEAD method handling
- Normalize raw footage paths in BrollVideo.tsx and ensure generate_mock_clip creates disk assets to prevent Remotion delayRender timeouts
- Direct UI video player and download button to fresh H.264 artifact URLs with cache-busting
- All unit tests passing
```

### Commit Details

* **Type:** `fix`
* **Scope:** `engine`
* **Title:** `switch to H.264 video codec, resolve artifact paths, and fix missing footage fallbacks`
* **Key Changes:**
  * `incubrix/runner.py`: Replaced `-c:v mpeg4` with `-c:v libopenh264 -pix_fmt yuv420p` across preview and montage renderers.
  * `incubrix/footage.py`: Restored `generate_mock_clip` on search miss or mock mode so Remotion assets always resolve on disk.
  * `incubrix/api.py`: Multi-location artifact path lookup, HEAD method support, and `ensure_h264_playable` verification.
  * `remotion/BrollVideo.tsx`: Sanitized footage path prefixes to avoid 404s in Remotion bundler server.
  * `static/index.html`: Wired `showSelectedVideo(job)` to display player and download links upon completion.
  * `github/commits.md`: Updated release notes.
