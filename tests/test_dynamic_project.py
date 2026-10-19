"""Tests for dynamic per-job Remotion project generation and multi-script isolation."""

import json
from pathlib import Path
import subprocess
import pytest

from incubrix.audio import process_job_audio
from incubrix.project_generator import (
    ProjectGenerationError,
    setup_job_remotion_project,
    validate_job_remotion_project,
)


@pytest.mark.asyncio
async def test_dynamic_project_generation_two_distinct_scripts(tmp_path: Path):
    """Verify that two distinct scripts produce completely distinct, isolated Remotion projects."""

    # -------------------------------------------------------------------------
    # Job 1: Script A (2 scenes)
    # -------------------------------------------------------------------------
    job1_id = "job_test_script_a_001"
    job1_dir = tmp_path / job1_id
    job1_workspace = job1_dir / "workspace"
    job1_artifacts = job1_dir / "artifacts"

    script1 = "Yesterday I covered Microsoft new decision model. It returns typed answers right away."
    req1 = {
        "script": script1,
        "voice": "en-IN-female",
        "aspect_ratios": ["16:9", "9:16"],
        "style": "developer",
    }

    res1 = await process_job_audio(
        job_id=job1_id,
        job_request=req1,
        workspace_dir=job1_workspace,
        artifacts_dir=job1_artifacts,
        mock=True,
    )

    proj1 = setup_job_remotion_project(
        job_id=job1_id,
        workspace_dir=job1_workspace,
        captions_data=res1["captions"],
        aspect_ratios=["16:9", "9:16"],
        theme_name="developer",
    )

    assert proj1["validation"]["valid"] is True
    assert proj1["job_config"]["scene_count"] == 2
    assert proj1["job_config"]["job_id"] == job1_id

    # -------------------------------------------------------------------------
    # Job 2: Script B (3 scenes)
    # -------------------------------------------------------------------------
    job2_id = "job_test_script_b_002"
    job2_dir = tmp_path / job2_id
    job2_workspace = job2_dir / "workspace"
    job2_artifacts = job2_dir / "artifacts"

    script2 = (
        "Database migrations do not have to be slow. "
        "Automatic schema diffing saves hours on every deploy! "
        "Try it on your next production release."
    )
    req2 = {
        "script": script2,
        "voice": "en-US-female",
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "style": "ink",
    }

    res2 = await process_job_audio(
        job_id=job2_id,
        job_request=req2,
        workspace_dir=job2_workspace,
        artifacts_dir=job2_artifacts,
        mock=True,
    )

    proj2 = setup_job_remotion_project(
        job_id=job2_id,
        workspace_dir=job2_workspace,
        captions_data=res2["captions"],
        aspect_ratios=["16:9", "9:16", "1:1"],
        theme_name="ink",
    )

    assert proj2["validation"]["valid"] is True
    assert proj2["job_config"]["scene_count"] == 3
    assert proj2["job_config"]["job_id"] == job2_id

    # -------------------------------------------------------------------------
    # Verification of Distinction and Complete Isolation
    # -------------------------------------------------------------------------
    # 1. Scene counts differ
    assert len(res1["captions"]["scenes"]) == 2
    assert len(res2["captions"]["scenes"]) == 3

    # 2. Total duration and frames differ
    assert res1["captions"]["totalFrames"] != res2["captions"]["totalFrames"]

    # 3. Text content is completely distinct
    assert "Microsoft" in res1["captions"]["scenes"][0]["voiceText"]
    assert "Database migrations" in res2["captions"]["scenes"][0]["voiceText"]

    # 4. Job 1 files remain unaffected by Job 2
    with open(job1_workspace / "job_config.json", "r") as f:
        cfg1 = json.load(f)
    assert cfg1["scene_count"] == 2
    assert cfg1["job_id"] == job1_id

    with open(job2_workspace / "job_config.json", "r") as f:
        cfg2 = json.load(f)
    assert cfg2["scene_count"] == 3
    assert cfg2["job_id"] == job2_id

    # 5. Test that Remotion CLI can discover compositions directly in job1 workspace
    cmd = ["npx", "remotion", "compositions", "index.ts"]
    proc = subprocess.run(
        cmd,
        cwd=str(job1_workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode == 0, f"Remotion failed: {proc.stderr}"
    assert "Broll-16x9" in proc.stdout
    assert "Broll-9x16" in proc.stdout
    assert "Broll-1x1" in proc.stdout


def test_validate_job_remotion_project_fails_on_missing_files(tmp_path: Path):
    """Verify validation raises ProjectGenerationError when required assets are missing."""
    empty_workspace = tmp_path / "empty_job"
    empty_workspace.mkdir(parents=True, exist_ok=True)

    with pytest.raises(ProjectGenerationError):
        validate_job_remotion_project(empty_workspace)
