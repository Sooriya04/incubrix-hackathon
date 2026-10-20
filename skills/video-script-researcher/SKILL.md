---
name: video-script-researcher
description: >-
  Researches topics and generates multi-scene documentary narration scripts
  matching exact duration specifications (e.g. 30s, 1:00 min, 1:30 min, 3:00 min).
  Calculates word budget, generates visual keywords for B-roll, and strictly strips
  all robotic 'Scene 1' markers from spoken audio.
---

# Video Script Researcher & Duration Calibration Skill

This skill governs how topics and time requests (e.g., `Explain AI agents (3 minutes)`) are researched, budgeted into word counts, divided into scenes, and converted into lockstep Remotion videos.

---

## 1. Pacing & Word Budget Calculation

Spoken English for video narration averages **130 to 150 words per minute** (~2.3 words per second). Always calculate word budgets before writing:

| Target Duration | Seconds | Word Budget | Recommended Scenes | Average Words / Scene |
| :--- | :--- | :--- | :--- | :--- |
| **30 sec** | 30s | ~65 – 75 words | 2 – 3 scenes | 25 – 30 words |
| **1:00 min** | 60s | ~130 – 150 words | 4 – 5 scenes | 30 – 35 words |
| **1:30 min** | 90s | ~200 – 220 words | 6 – 7 scenes | 30 – 35 words |
| **2:00 min** | 120s | ~270 – 290 words | 8 – 9 scenes | 30 – 35 words |
| **3:00 min** | 180s | ~400 – 430 words | 10 – 12 scenes | 35 – 40 words |
| **5:00 min** | 300s | ~650 – 720 words | 15 – 18 scenes | 35 – 40 words |

---

## 2. Critical Scriptwriting Rules (No Robotic Markers)

> [!IMPORTANT]
> Text-to-speech engines read every single token aloud. Meta-labels ruin the video.

1. **NEVER output Scene Headers in Spoken Audio:**
   - ❌ WRONG: `"Scene 1: Artificial intelligence is transforming software engineering."`
   - ❌ WRONG: `"[Scene 01] Deep learning networks process vast data."`
   - ❌ WRONG: `"Narrator: Today we explore autonomous agents."`
   - ✅ CORRECT: `"Artificial intelligence is transforming software engineering."`
2. **Clean Natural Prose:**
   - Write in direct, engaging, declarative sentences.
   - Avoid parenthetical notes `(pause 2 seconds)` or markdown stage directions `*whispering*`.
3. **Dedicated Visual Hints per Scene:**
   - For every scene paragraph, assign 3–5 concrete stock footage search keywords.
   - Example keywords: `datacenter server rack lights`, `software engineer code terminal`, `robotic arm manufacturing`.

---

## 3. Structural Arc for 1:30 to 3:00 Minute Videos

When researching and structuring a topic:
- **Hook (Scene 1):** The core problem or counter-intuitive hook.
- **Core Mechanism (Scenes 2–4):** Architecture, mechanics, or how it works under the hood.
- **Operational Reality (Scenes 5–7):** Real-world workflows, data processing, and tools.
- **Impact & Future (Final Scenes):** Quantitative metrics, long-term impact, and closing key takeaway.

---

## 4. Antigravity Prompt Template

When invoking Antigravity CLI (`gemini-3.8-flash-high`) to research and generate:

```bash
agy --effort low -p "You are an expert technical documentary scriptwriter.
Research and write an engaging voiceover script explaining: '{topic}'.
Target duration: {duration_sec} seconds (~{target_words} words across {target_scenes} scenes).

STRICT RULES:
1. Output ONLY the pure spoken narration sentences, separated by double newlines between scenes.
2. DO NOT include 'Scene 1', 'Narrator:', headings, bullets, or timestamps.
3. Every sentence will be synthesized directly into speech audio."
```
