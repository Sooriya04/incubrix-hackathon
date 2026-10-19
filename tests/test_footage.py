"""Tests for Footage Discovery, Licensing Guardrails, and Rate-Limiting."""

import asyncio
from pathlib import Path
import pytest

from incubrix.config import settings
from incubrix.footage import (
    clean_search_query,
    generate_mock_clip,
    PixabayClient,
    process_job_footage,
)


def test_clean_search_query():
    assert clean_search_query("A developer writing code in a terminal") == "developer writing"
    assert clean_search_query("Modern microservices architecture in the cloud") == "modern microservices"
    assert clean_search_query(None) == "technology"
    assert clean_search_query("") == "technology"


@pytest.mark.asyncio
async def test_generate_mock_clip(tmp_path: Path):
    out_mp4 = tmp_path / "test_clip.mp4"
    res = await generate_mock_clip(out_mp4, duration_sec=1.5)
    assert res.exists()
    assert res.stat().st_size > 500


@pytest.mark.asyncio
async def test_pixabay_caching_and_avoid_filtering(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    client = PixabayClient(api_key="dummy_key", cache_dir=cache_dir)

    # Pre-seed query cache with mock hits (no network calls)
    cache_file = client._query_cache_path("developer code")
    mock_hits = [
        {
            "id": 101,
            "duration": 10,
            "tags": "developer, code, computer, software",
            "pageURL": "https://pixabay.com/videos/101",
            "user": "CodeDev",
            "videos": {
                "large": {"url": "https://cdn.pixabay.com/test_101.mp4", "width": 1920, "height": 1080}
            },
        },
        {
            "id": 102,
            "duration": 8,
            "tags": "people, face, close-up, smile",
            "pageURL": "https://pixabay.com/videos/102",
            "user": "FaceCreator",
            "videos": {
                "large": {"url": "https://cdn.pixabay.com/test_102.mp4", "width": 1920, "height": 1080}
            },
        },
    ]
    import json
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump({"query": "developer code", "hits": mock_hits}, f)

    # 1. Search without avoid -> both return
    hits_all = await client.search_videos("developer code")
    assert len(hits_all) == 2

    # 2. Search with avoid=["face", "people"] -> only code hit returns
    hits_filtered = await client.search_videos("developer code", avoid=["face", "people"])
    assert len(hits_filtered) == 1
    assert hits_filtered[0]["id"] == 101


@pytest.mark.asyncio
async def test_process_job_footage_mock(tmp_path: Path):
    workspace = tmp_path / "workspace"
    scenes = [
        {
            "id": 1,
            "durationSec": 2.5,
            "visual_hint": "server racks in datacenter",
            "voiceText": "Backend servers run continuously.",
        },
        {
            "id": 2,
            "durationSec": 3.0,
            "visual_hint": "developer terminal",
            "voiceText": "Every line is tested.",
        },
    ]

    enriched = await process_job_footage(scenes, workspace_dir=workspace, mock=True)
    assert len(enriched) == 2

    for s in enriched:
        assert s["footageUrl"] is not None
        assert s["clip"] is not None
        assert s["clip"]["license"]["commercial_use_allowed"] is True
        # Verify physical video file was created in workspace
        video_file = workspace / "public" / s["footageUrl"]
        assert video_file.exists()
        assert video_file.stat().st_size > 500
