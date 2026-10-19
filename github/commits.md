# Git Commit

## Commit Command

```bash
git add .
git commit -m "feat(remotion): make scene titles, headlines, and visual cues 100% dynamic from script

- Remove generic placeholder titles from incubrix/audio.py segment_script_into_scenes
- Update BrollVideo.tsx FallbackPlateScene to render dynamic headline, topic badge, and visual cue directly from scene data
- Support full video footage layers and dynamic developer visual components without hardcoded text
- Verified 27 automated tests passing and rendered frame-accurate still"
```

---

## Commit Details

* **Type:** `feat`
* **Scope:** `remotion`
* **Title:** `make scene titles, headlines, and visual cues 100% dynamic from script`
* **Files Included:**
  * `incubrix/audio.py`: Dynamic title extraction from sentence tokens in `segment_script_into_scenes`
  * `remotion/BrollVideo.tsx`: Dynamic headline, topic badge, and visual cue rendering in `FallbackPlateScene`
  * `remotion/components/Counter.tsx`: Stat counter with cubic easing for metric scenes
  * `remotion/components/Cross.tsx`: SVG danger cross mark for friction scenes
  * `phase.md`: Updated Phase 3 Task 3.1 documentation
  * `github/commits.md`: Single commit tracking file
