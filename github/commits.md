# Git Commit

## Commit Command

```bash
git add .
git commit -m "feat(audio): implement Phase 2 Task 2.2 audio voiceover and subtitle alignment engine

- Implement neural TTS synthesis via edge-tts with Indian English (Neerja/Prabhat) and US voices
- Mirror file structure from /media/workspace/shorts/decision_model_ms (scene_*.mp3, voiceover.mp3, sceneMetadata.json, subtitles.json, captions.json)
- Implement instant duration-weighted word boundary alignment (<1ms) replacing heavy Whisper STT
- Generate standard SubRip Subtitle file (captions.srt) and contract-compliant timeline.json / manifest.json
- Wire process_job_audio into background JobRunner execution pipeline
- Add comprehensive test suite in tests/test_audio.py (26 total test cases passing)"
```

---

## Commit Details

* **Type:** `feat`
* **Scope:** `audio`
* **Title:** `implement Phase 2 Task 2.2 audio voiceover and subtitle alignment engine`
* **Files Included:**
  * `incubrix/audio.py`: Speech synthesis, scene segmentation, duration-weighted word boundary alignment, unified audio concatenator, and caption/timeline/manifest generator
  * `incubrix/runner.py`: Pipeline integration wiring `process_job_audio` directly into `run_job`
  * `tests/test_audio.py`: 7 unit and integration tests covering SRT timestamps, script segmentation, word boundaries, pipeline generation, and artifact consistency
  * `phase.md`: Phase 2 implementation documentation and verification logs
  * `github/commits.md`: Single commit tracking documentation
