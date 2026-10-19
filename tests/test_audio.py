"""Tests for the Phase 2 audio generation and subtitle alignment pipeline."""

import json
from pathlib import Path
import pytest

from incubrix.audio import (
    build_audio_pipeline,
    compute_word_timings,
    extract_scenes_from_request,
    format_srt_timestamp,
    generate_timeline_and_manifest,
    get_audio_duration,
    process_job_audio,
    segment_script_into_scenes,
    synthesize_scene_audio,
)


def test_format_srt_timestamp():
    """Verify SRT timestamp formatting according to SubRip spec."""
    assert format_srt_timestamp(0.0) == "00:00:00,000"
    assert format_srt_timestamp(3.42) == "00:00:03,420"
    assert format_srt_timestamp(65.123) == "00:01:05,123"
    assert format_srt_timestamp(3661.05) == "01:01:01,050"


def test_segment_script_into_scenes():
    """Test splitting raw scripts into semantic scenes with metadata."""
    script = "Saving money doesn't have to be complicated. It starts with understanding where every rupee goes! Take control today."
    scenes = segment_script_into_scenes(script)
    assert len(scenes) == 3
    assert scenes[0]["id"] == 1
    assert scenes[0]["name"] == "Scene01"
    assert "Saving money doesn't have to be complicated" in scenes[0]["text"]
    assert scenes[1]["id"] == 2
    assert "every rupee goes" in scenes[1]["text"]
    assert scenes[2]["id"] == 3
    assert "Take control today" in scenes[2]["text"]

    # Test empty or single sentence
    assert segment_script_into_scenes("") == []
    single = segment_script_into_scenes("Only one sentence here.")
    assert len(single) == 1
    assert single[0]["text"] == "Only one sentence here."


def test_extract_scenes_from_request():
    """Verify extracting scenes from structured list vs raw script."""
    # From scenes list
    req_scenes = {
        "scenes": [
            {"text": "Intro text", "visual_hint": "Tech visual"},
            {"text": "Outro text", "visual_hint": "Subscribe visual"},
        ]
    }
    extracted = extract_scenes_from_request(req_scenes)
    assert len(extracted) == 2
    assert extracted[0]["text"] == "Intro text"
    assert extracted[0]["visual_hint"] == "Tech visual"
    assert extracted[1]["text"] == "Outro text"

    # From script string
    req_script = {"script": "First scene. Second scene."}
    extracted_script = extract_scenes_from_request(req_script)
    assert len(extracted_script) == 2
    assert extracted_script[0]["text"] == "First scene."
    assert extracted_script[1]["text"] == "Second scene."


def test_compute_word_timings():
    """Verify instant duration-weighted word boundary computation."""
    text = "Saving money is easy"
    duration = 2.0
    words = compute_word_timings(duration, text)

    assert len(words) == 4
    assert words[0]["word"] == "Saving"
    assert words[-1]["word"] == "easy"
    # Ensure sequential timestamps
    for i in range(len(words) - 1):
        assert words[i]["start"] < words[i]["end"]
        assert words[i]["end"] <= words[i + 1]["start"] + 0.05
    assert words[-1]["end"] <= duration


@pytest.mark.asyncio
async def test_synthesize_scene_audio_mock(tmp_path: Path):
    """Verify fast mock audio synthesis produces playable MP3 with duration."""
    out_file = tmp_path / "mock_scene.mp3"
    await synthesize_scene_audio("Test audio phrase", "en-IN-female", out_file, mock=True)
    assert out_file.exists()
    assert out_file.stat().st_size > 0
    duration = get_audio_duration(out_file)
    assert duration > 1.0


@pytest.mark.asyncio
async def test_build_audio_pipeline(tmp_path: Path):
    """Verify build_audio_pipeline creates exact decision_model_ms structure."""
    scenes_data = [
        {"id": 1, "text": "Yesterday I covered Microsoft's new decision model.", "visual_hint": "Title card"},
        {"id": 2, "text": "It returns typed answers with high confidence.", "visual_hint": "Graph visual"},
    ]

    result = await build_audio_pipeline(
        scenes_data=scenes_data,
        voice="en-IN-female",
        workspace_dir=tmp_path,
        mock=True,
    )

    # 1. Check directory structure
    public_audio = tmp_path / "public" / "audio"
    src_dir = tmp_path / "src"
    artifacts_dir = tmp_path / "artifacts"

    assert (public_audio / "scene_01.mp3").exists()
    assert (public_audio / "scene_02.mp3").exists()
    assert (tmp_path / "public" / "voiceover.mp3").exists()

    # 2. Check metadata JSON
    meta_file = src_dir / "sceneMetadata.json"
    assert meta_file.exists()
    with open(meta_file, "r") as f:
        meta = json.load(f)
    assert meta["fps"] == 30
    assert len(meta["scenes"]) == 2
    assert meta["totalFrames"] > 0
    assert meta["totalDurationSec"] > 0

    # 3. Check subtitles JSON
    subs_file = src_dir / "subtitles.json"
    assert subs_file.exists()
    with open(subs_file, "r") as f:
        subs = json.load(f)
    assert "scene_01.mp3" in subs
    assert "scene_02.mp3" in subs

    # 4. Check captions JSON
    captions_file = src_dir / "captions.json"
    assert captions_file.exists()
    with open(captions_file, "r") as f:
        captions = json.load(f)
    assert len(captions["scenes"]) == 2
    assert len(captions["words"]) > 0

    # 5. Check SRT file
    srt_file = artifacts_dir / "captions.srt"
    assert srt_file.exists()
    srt_content = srt_file.read_text()
    assert "-->" in srt_content
    assert "decision model" in srt_content


@pytest.mark.asyncio
async def test_process_job_audio_integration(tmp_path: Path):
    """Verify full process_job_audio orchestrator produces all contract artifacts."""
    job_id = "test_audio_job_12345"
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"

    job_request = {
        "script": "Automated video generation is now live. Every scene is timed with neural audio.",
        "voice": "en-IN-female",
        "aspect_ratios": ["16:9", "9:16"],
    }

    res = await process_job_audio(
        job_id=job_id,
        job_request=job_request,
        workspace_dir=workspace_dir,
        artifacts_dir=artifacts_dir,
        mock=True,
    )

    # Deliverables in artifacts/
    assert (artifacts_dir / "captions.srt").exists()
    assert (artifacts_dir / "timeline.json").exists()
    assert (artifacts_dir / "manifest.json").exists()

    # Verify timeline.json schema
    with open(artifacts_dir / "timeline.json", "r") as f:
        tl = json.load(f)
    assert tl["job_id"] == job_id
    assert tl["scene_count"] == 2
    assert len(tl["scenes"]) == 2
    assert "clip" in tl["scenes"][0]
    assert "relevance_score" in tl["scenes"][0]

    # Verify manifest.json schema
    with open(artifacts_dir / "manifest.json", "r") as f:
        mf = json.load(f)
    assert mf["job_id"] == job_id
    assert "models_and_providers" in mf
    assert "cost_breakdown" in mf
    assert "licensing_summary" in mf
