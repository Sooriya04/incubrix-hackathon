"""Tests for automated Remotion video rendering and multi-aspect ratio delivery."""

import asyncio
from pathlib import Path
import httpx
import pytest

from incubrix.config import settings
from incubrix.runner import COMPOSITION_MAP, render_remotion_ratio


@pytest.mark.asyncio
async def test_mock_automatic_remotion_rendering_multi_ratio(client: httpx.AsyncClient, isolated_storage, monkeypatch):
    """Verify that submitting a job renders and delivers MP4s for all requested aspect ratios."""
    monkeypatch.setattr(settings, "AGY_MOCK", True)
    monkeypatch.setattr(settings, "REQUIRE_IDEMPOTENCY_KEY", False)

    payload = {
        "script": "Automatic video rendering is now connected. Multi-aspect video delivery is fully active.",
        "voice": "en-IN-female",
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "style": "developer",
    }

    res = await client.post("/api/v1/broll/jobs", json=payload)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    # Poll status until completion
    data = None
    for _ in range(40):
        res_get = await client.get(f"/api/v1/jobs/{job_id}")
        assert res_get.status_code == 200
        data = res_get.json()
        if data["status"] in ["succeeded", "failed"]:
            break
        await asyncio.sleep(0.1)

    assert data is not None
    assert data["status"] == "succeeded", f"Job failed: {data.get('error')}"
    assert data["progress"] == 100
    assert data["stage"] == "completed"

    artifacts = data["artifacts"]
    assert "videos" in artifacts
    assert "16:9" in artifacts["videos"]
    assert "9:16" in artifacts["videos"]
    assert "1:1" in artifacts["videos"]

    artifacts_dir = isolated_storage["jobs_dir"] / job_id / "artifacts"

    # Verify physical file existence and playability
    for ratio in ["16:9", "9:16", "1:1"]:
        safe_name = ratio.replace(":", "_")
        video_file = artifacts_dir / f"video_{safe_name}.mp4"
        assert video_file.exists()
        assert video_file.stat().st_size > 1000

        # Verify artifact download endpoint works
        dl_res = await client.get(f"/api/v1/jobs/{job_id}/artifacts/video_{safe_name}.mp4")
        assert dl_res.status_code == 200
        assert dl_res.headers.get("content-type") == "video/mp4"
        assert len(dl_res.content) > 1000


@pytest.mark.asyncio
async def test_renderer_failure_handling(tmp_path: Path):
    """Verify that renderer failures raise errors and prevent falsely succeeding."""
    bad_workspace = tmp_path / "bad_workspace"
    bad_workspace.mkdir(parents=True, exist_ok=True)
    out_file = tmp_path / "artifacts" / "video_bad.mp4"

    # Test non-existent composition in real mode
    with pytest.raises(Exception):
        await render_remotion_ratio(
            workspace_dir=bad_workspace,
            composition_id="NonExistentComp",
            output_mp4=out_file,
            timeout_seconds=5.0,
            mock=False,
        )


@pytest.mark.asyncio
async def test_real_remotion_render_single_ratio(client: httpx.AsyncClient, isolated_storage, monkeypatch):
    """Test actual real Remotion render through the runner without mocking the video step."""
    monkeypatch.setattr(settings, "AGY_MOCK", True)  # Mock LLM check, but use real Remotion
    monkeypatch.setattr(settings, "REQUIRE_IDEMPOTENCY_KEY", False)
    monkeypatch.setattr(settings, "JOB_TIMEOUT_SECONDS", 120)

    # Temporary monkeypatch to run real Remotion while keeping LLM mock
    original_render = render_remotion_ratio

    async def _real_render_wrapper(workspace_dir, composition_id, output_mp4, timeout_seconds, mock):
        return await original_render(
            workspace_dir=workspace_dir,
            composition_id=composition_id,
            output_mp4=output_mp4,
            timeout_seconds=timeout_seconds,
            mock=False,  # Force real Remotion render!
        )

    monkeypatch.setattr("incubrix.runner.render_remotion_ratio", _real_render_wrapper)

    payload = {
        "script": "Testing real Remotion video engine export. Pure flat plate typography.",
        "voice": "en-IN-female",
        "aspect_ratios": ["16:9"],
        "style": "developer",
    }

    res = await client.post("/api/v1/broll/jobs", json=payload)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    # Poll status until completion (real render takes 10-25s)
    data = None
    for _ in range(60):
        res_get = await client.get(f"/api/v1/jobs/{job_id}")
        assert res_get.status_code == 200
        data = res_get.json()
        if data["status"] in ["succeeded", "failed"]:
            break
        await asyncio.sleep(1.0)

    assert data is not None
    assert data["status"] == "succeeded", f"Real render failed: {data.get('error')}"

    video_file = isolated_storage["jobs_dir"] / job_id / "artifacts" / "video_16_9.mp4"
    assert video_file.exists()
    assert video_file.stat().st_size > 100000  # Real 1080p video > 100KB
