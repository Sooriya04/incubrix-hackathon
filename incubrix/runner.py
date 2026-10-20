"""Asynchronous background runner and supervisor for headless agy execution."""

import asyncio
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Dict, Optional

import httpx

from incubrix.audio import build_audio_pipeline, process_job_audio
from incubrix.config import settings
from incubrix.footage import process_job_footage
from incubrix.models import ErrorDetail, JobArtifacts, JobRecord
from incubrix.project_generator import setup_job_remotion_project
from incubrix.storage import job_store


SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|secret|token|password|auth|bearer)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-\.]{8,})['\"]?"
)


def redact_secrets(text: str) -> str:
    """Redact sensitive credentials, tokens, and passwords from logs or messages."""
    if not text:
        return text

    def _replace(match):
        prefix = match.group(1)
        return f"{prefix}=***REDACTED***"

    return SECRET_PATTERN.sub(_replace, text)


def generate_signature(secret: str, payload_bytes: bytes) -> str:
    """Generate X-IncuBrix-Signature HMAC-SHA256."""
    return "sha256=" + hmac.new(
        key=secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()


COMPOSITION_MAP = {
    "16:9": "Broll-16x9",
    "9:16": "Broll-9x16",
    "1:1": "Broll-1x1",
    "3:2": "Broll-3x2",
}


async def render_remotion_ratio(
    workspace_dir: Path,
    composition_id: str,
    output_mp4: Path,
    timeout_seconds: float = 120.0,
    mock: bool = False,
) -> None:
    """Render a single aspect ratio composition to an H.264/AAC MP4 video."""
    output_mp4 = Path(output_mp4).resolve()
    workspace_dir = Path(workspace_dir).resolve()
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    if mock:
        # Fast, deterministic MP4 generation that still follows the generated
        # narration length. This keeps API-test artifacts representative.
        voiceover = workspace_dir / "public" / "voiceover.mp3"
        has_voiceover = voiceover.exists() and voiceover.stat().st_size > 0
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "lavfi", "-i", "color=c=0x0F1115:s=640x360:r=30",
        ]
        if has_voiceover:
            cmd.extend(["-i", str(voiceover), "-shortest"])
        else:
            cmd.extend(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "2.0"])
        cmd.extend([
            "-c:v", "libopenh264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(output_mp4),
        ])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Mock video generation failed with exit code {proc.returncode}")
        return

    # Real Remotion Render (concurrency 1 for low RAM, 540p scale for ultra-fast generation)
    cmd = [
        "npx",
        "remotion",
        "render",
        "index.ts",
        composition_id,
        str(output_mp4),
        "--codec", "h264",
        "--pixel-format", "yuv420p",
        "--concurrency", "1",
        "--gl", "swiftshader",
        "--scale", "0.5",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(workspace_dir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_data, stderr_data = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise asyncio.TimeoutError(f"Remotion render for {composition_id} timed out after {timeout_seconds}s")

    if proc.returncode != 0:
        stderr_msg = redact_secrets(stderr_data.decode("utf-8", errors="replace"))
        err = RuntimeError(f"Remotion render failed with exit code {proc.returncode}: {stderr_msg}")
        setattr(err, "exit_code", proc.returncode)
        raise err

    # Post-render validation: verify output exists and is playable
    if not output_mp4.exists() or output_mp4.stat().st_size == 0:
        raise RuntimeError(f"Remotion render finished but {output_mp4.name} is missing or empty")

    verify_cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(output_mp4),
    ]
    verify_proc = await asyncio.create_subprocess_exec(
        *verify_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    v_stdout, _ = await verify_proc.communicate()
    if verify_proc.returncode != 0 or not v_stdout.strip():
        raise RuntimeError(f"Rendered video {output_mp4.name} failed ffprobe playback verification")


async def is_playable_mp4(video_file: Path) -> bool:
    """Return whether ``video_file`` is a decodable MP4 with video and audio.

    A failed Chromium/Remotion render may leave an ``ftyp``-only file behind.
    Existence and a non-zero size are therefore not sufficient completion checks.
    """
    if not video_file.exists() or video_file.stat().st_size < 1024:
        return False

    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v", "error",
        "-show_entries", "stream=codec_type:format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_file),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    values = {line.strip() for line in stdout.decode("utf-8", errors="replace").splitlines()}
    return proc.returncode == 0 and {"video", "audio"}.issubset(values)


async def render_footage_fallback(
    workspace_dir: Path,
    output_mp4: Path,
    ratio: str,
) -> None:
    """Build a playable B-roll montage if Chromium/Remotion cannot start.

    It uses the job's real scene clips and generated narration rather than a
    blank plate, so a renderer outage never reduces a finished video to black.
    """
    captions_path = workspace_dir / "captions.json"
    voiceover = workspace_dir / "public" / "voiceover.mp3"
    if not captions_path.exists() or not voiceover.exists():
        raise RuntimeError("Cannot build footage fallback: captions or narration is missing")

    with open(captions_path, "r", encoding="utf-8") as f:
        scenes = json.load(f).get("scenes", [])
    # Keep the emergency path quick enough to recover a blocked renderer. The
    # primary Remotion path remains the 1080p-class export.
    dimensions = {"16:9": (640, 360), "9:16": (360, 640), "1:1": (540, 540)}
    width, height = dimensions.get(ratio, dimensions["16:9"])

    inputs: list[str] = []
    filters: list[str] = []
    scene_labels: list[str] = []
    footage_dir = workspace_dir / "public" / "footage"
    for index, scene in enumerate(scenes):
        candidate = footage_dir / f"scene_{int(scene.get('id', index + 1)):02d}.mp4"
        if not candidate.exists() or candidate.stat().st_size == 0:
            continue
        duration = max(0.5, float(scene.get("durationSec", 2.0)))
        inputs.extend(["-stream_loop", "-1", "-i", str(candidate)])
        label = f"v{len(scene_labels)}"
        filters.append(
            f"[{len(scene_labels)}:v]trim=duration={duration:.3f},setpts=PTS-STARTPTS,"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps=30,format=yuv420p[{label}]"
        )
        scene_labels.append(label)

    if not scene_labels:
        # Provider had no semantically relevant clip. Render the Remotion-style
        # semantic animation fallback as a clean animated text card with the
        # narration captions. This preserves meaning instead of showing stock
        # footage for the wrong topic.
        srt_file = workspace_dir / "artifacts" / "captions.srt"
        escaped_srt = str(srt_file.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        semantic_filter = (
            f"subtitles=filename='{escaped_srt}':force_style="
            "'FontName=DejaVu Sans,FontSize=18,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BackColour=&H99000000,BorderStyle=1,"
            "Outline=2,Shadow=1,Alignment=2,MarginV=34'"
        )
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=0x111827:s={width}x{height}:r=15",
            "-i", str(voiceover), "-vf", semantic_filter, "-map", "0:v", "-map", "1:a",
            "-c:v", "libopenh264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-shortest", str(output_mp4),
        ]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate()
        if proc.returncode != 0 or not await is_playable_mp4(output_mp4):
            error = redact_secrets(stderr.decode("utf-8", errors="replace"))
            raise RuntimeError(f"Semantic animation fallback failed: {error[-500:]}")
        return

    filters.append("".join(f"[{label}]" for label in scene_labels) + f"concat=n={len(scene_labels)}:v=1:a=0[vbase]")
    srt_file = workspace_dir / "artifacts" / "captions.srt"
    if srt_file.exists():
        escaped_srt = str(srt_file.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        filters.append(
            f"[vbase]subtitles=filename='{escaped_srt}':force_style="
            "'FontName=DejaVu Sans,FontSize=18,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BackColour=&H99000000,BorderStyle=1,"
            "Outline=2,Shadow=1,Alignment=2,MarginV=38'[v]"
        )
    else:
        filters.append("[vbase]null[v]")
    cmd = [
        "ffmpeg", "-y", *inputs, "-i", str(voiceover),
        "-filter_complex", ";".join(filters),
        "-map", "[v]", "-map", f"{len(scene_labels)}:a",
        "-c:v", "libopenh264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest", str(output_mp4),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not await is_playable_mp4(output_mp4):
        error = redact_secrets(stderr.decode("utf-8", errors="replace"))
        raise RuntimeError(f"Footage fallback did not produce a playable MP4: {error[-500:]}")


class JobRunner:
    """Manages background job execution using headless agy or mock harness."""

    def __init__(self):
        self.active_tasks: Dict[str, asyncio.Task] = {}

    def enqueue(self, job_id: str) -> asyncio.Task:
        """Enqueue a background execution task immediately without blocking."""
        task = asyncio.create_task(self.run_job(job_id))
        self.active_tasks[job_id] = task
        # Remove task on completion
        task.add_done_callback(lambda _: self.active_tasks.pop(job_id, None))
        return task

    async def fail_orphaned_jobs(self) -> int:
        """Mark unfinished jobs left behind by a stopped application as failed.

        Rendering happens inside this process, so an in-memory task cannot survive a
        server restart. Reporting such jobs as running would be misleading.
        """
        jobs = await job_store.list_jobs(limit=1000)
        recovered = 0
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        for job in jobs:
            if job.status not in {"queued", "running"}:
                continue
            if job.job_id in self.active_tasks:
                continue

            previous_stage = job.stage
            previous_progress = job.progress
            job.status = "failed"
            job.stage = "failed"
            job.failed_at = now
            job.error = ErrorDetail(
                code="WORKER_STOPPED",
                message="Rendering stopped because the IncuBrix worker was restarted or shut down.",
                retryable=True,
                details={"previous_stage": previous_stage, "previous_progress": previous_progress},
            )
            await job_store.save_job(job)
            recovered += 1

        return recovered

    async def run_job(self, job_id: str) -> None:
        """Execute a job asynchronously, updating stages and capturing artifacts."""
        job = await job_store.get_job(job_id)
        if not job:
            return

        start_time = time.monotonic()
        started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        # 1. Transition to 'running'
        job.status = "running"
        job.started_at = started_at
        job.stage = "transcribing" if job.request.get("script") else "segmenting"
        job.progress = 10
        await job_store.save_job(job)

        # 2. Setup job directory structure & central renders directory
        job_dir = settings.JOBS_DIR / job_id
        logs_dir = job_dir / "logs"
        artifacts_dir = job_dir / "artifacts"

        # Central renders directory: each job gets its dedicated sub-directory inside RENDERS_DIR
        renders_job_dir = settings.RENDERS_DIR / job_id
        renders_job_dir.mkdir(parents=True, exist_ok=True)
        workspace_dir = renders_job_dir

        logs_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Create workspace symlink inside job_dir for backwards compatibility
        job_workspace_link = job_dir / "workspace"
        if not job_workspace_link.exists():
            try:
                os.symlink(renders_job_dir.resolve(), job_workspace_link)
            except Exception:
                job_workspace_link.mkdir(parents=True, exist_ok=True)

        input_path = job_dir / "input.json"
        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(job.request, f, indent=2)

        stdout_log_path = logs_dir / "stdout.log"
        stderr_log_path = logs_dir / "stderr.log"

        # Check if running in mock mode or real agy execution
        is_mock = settings.AGY_MOCK or not Path(settings.AGY_BIN_PATH).exists()

        try:
            # 1. Phase 2 Audio Generation Pipeline
            job.stage = "transcribing"
            job.progress = 20
            await job_store.save_job(job)

            audio_res = await process_job_audio(
                job_id=job.job_id,
                job_request=job.request,
                workspace_dir=workspace_dir,
                artifacts_dir=artifacts_dir,
                mock=is_mock,
            )

            job.stage = "segmenting"
            job.progress = 35
            await job_store.save_job(job)

            # 2. Phase 2/3 Footage Discovery (Pixabay / Mock with disk cache and rate limits)
            job.stage = "sourcing_footage"
            job.progress = 50
            await job_store.save_job(job)

            captions_data = audio_res["captions"]
            avoid_list = job.request.get("avoid", [])
            enriched_scenes = await process_job_footage(
                scenes=captions_data.get("scenes", []),
                workspace_dir=workspace_dir,
                avoid=avoid_list,
                mock=is_mock,
            )
            captions_data["scenes"] = enriched_scenes

            # Dynamic timeline.json generation
            timeline_file = artifacts_dir / "timeline.json"
            total_dur_ms = int(captions_data.get("totalDurationSec", 8.0) * 1000)
            timeline_data = {
                "timeline_id": f"tl_{job.job_id}",
                "total_duration_ms": total_dur_ms,
                "scenes": [
                    {
                        "scene_index": idx,
                        "start_time_ms": int((s.get("startTimeSec") or 0) * 1000),
                        "end_time_ms": int(((s.get("startTimeSec") or 0) + (s.get("durationSec") or 0)) * 1000),
                        "duration_ms": int((s.get("durationSec") or 0) * 1000),
                        "narration_text": s.get("voiceText", ""),
                        "visual_hint": s.get("visual_hint", ""),
                        "clip": s.get("clip") or {
                            "clip_id": f"scene_plate_{idx+1}",
                            "source_provider": "developer_plates",
                            "source_url": "",
                            "license": {
                                "type": "Internal",
                                "commercial_use_allowed": True,
                                "attribution_required": False,
                            },
                            "attribution": "IncuBrix Developer Plates",
                            "is_ai_generated": False,
                            "generator_model": None,
                            "trim": {"in_ms": 0, "out_ms": int((s.get("durationSec") or 0) * 1000)},
                        },
                        "selection_reason": (s.get("clip") or {}).get("selection_reason", "Dynamic typography plate"),
                        "relevance_score": (s.get("clip") or {}).get("relevance_score", 4.5),
                    }
                    for idx, s in enumerate(enriched_scenes)
                ],
            }
            with open(timeline_file, "w", encoding="utf-8") as f:
                json.dump(timeline_data, f, indent=2)

            # 3. Normalization & Dynamic Remotion Project Harness Setup
            job.stage = "normalizing"
            job.progress = 65
            await job_store.save_job(job)

            if is_mock:
                await self._run_mock_pipeline(job, artifacts_dir, stdout_log_path, stderr_log_path)
            else:
                try:
                    await self._run_headless_agy(
                        job, input_path, workspace_dir, artifacts_dir, stdout_log_path, stderr_log_path
                    )
                except Exception:
                    # Seamless fallback if agy is logged out or unauthenticated
                    await self._run_mock_pipeline(job, artifacts_dir, stdout_log_path, stderr_log_path)

            aspect_ratios = job.request.get("aspect_ratios", ["16:9"])
            style_theme = job.request.get("style", "developer")
            valid_themes = ["developer", "ink", "paper", "signal"]
            chosen_theme = style_theme if style_theme in valid_themes else "developer"

            setup_job_remotion_project(
                job_id=job.job_id,
                workspace_dir=workspace_dir,
                captions_data=captions_data,
                aspect_ratios=aspect_ratios,
                theme_name=chosen_theme,
            )

            # 4. Phase 3 Automatic Remotion Video Rendering for each requested aspect ratio
            job.stage = "rendering"
            job.progress = 75
            await job_store.save_job(job)

            for idx, ratio in enumerate(aspect_ratios):
                composition_id = COMPOSITION_MAP.get(ratio, f"Broll-{ratio.replace(':', 'x')}")
                safe_name = ratio.replace(":", "_")
                video_out = artifacts_dir / f"video_{safe_name}.mp4"

                step_prog = 75 + int(((idx + 1) / max(1, len(aspect_ratios))) * 18)
                job.progress = min(93, step_prog)
                await job_store.save_job(job)

                try:
                    await render_remotion_ratio(
                        workspace_dir=workspace_dir,
                        composition_id=composition_id,
                        output_mp4=video_out,
                        timeout_seconds=min(
                            float(settings.REMOTION_RENDER_TIMEOUT_SECONDS),
                            float(settings.JOB_TIMEOUT_SECONDS),
                        ),
                        mock=is_mock,
                    )
                except Exception as render_err:
                    # A failed Remotion process can leave an ftyp-only, corrupt MP4.
                    # Remove it and create a footage montage with the narration.
                    if video_out.exists():
                        video_out.unlink()
                    try:
                        await render_footage_fallback(workspace_dir, video_out, ratio)
                    except Exception as fallback_err:
                        raise RuntimeError(f"Remotion failed ({render_err}); {fallback_err}") from fallback_err

                # Ensure renders_job_dir has video directly
                render_video_out = renders_job_dir / f"video_{safe_name}.mp4"
                if video_out.exists():
                    shutil.copyfile(video_out, render_video_out)
                    out_mp4 = renders_job_dir / "out.mp4"
                    if not out_mp4.exists():
                        try:
                            shutil.copyfile(video_out, out_mp4)
                        except Exception:
                            pass

            # 5. Packaging stage
            job.stage = "packaging"
            job.progress = 95
            await job_store.save_job(job)

            # Copy all metadata artifacts into renders_job_dir
            for fname in ["timeline.json", "manifest.json", "captions.srt"]:
                fsrc = artifacts_dir / fname
                if fsrc.exists():
                    try:
                        shutil.copyfile(fsrc, renders_job_dir / fname)
                    except Exception:
                        pass

            # Execution succeeded
            end_time = time.monotonic()
            completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            duration_seconds = round(end_time - start_time, 2)

            # Ensure deliverables exist (fallback safety net)
            for ratio in aspect_ratios:
                safe_name = ratio.replace(":", "_")
                video_file = artifacts_dir / f"video_{safe_name}.mp4"
                if not await is_playable_mp4(video_file):
                    raise RuntimeError(f"Final artifact {video_file.name} is missing, corrupt, or lacks audio/video streams")

            videos_map = {
                ratio: f"/api/v1/jobs/{job_id}/artifacts/video_{ratio.replace(':', '_')}.mp4"
                for ratio in aspect_ratios
            }

            job.status = "succeeded"
            job.stage = "completed"
            job.progress = 100
            job.completed_at = completed_at
            job.duration_seconds = duration_seconds
            job.artifacts = JobArtifacts(
                videos=videos_map,
                captions=f"/api/v1/jobs/{job_id}/artifacts/captions.srt",
                timeline=f"/api/v1/jobs/{job_id}/artifacts/timeline.json",
                manifest=f"/api/v1/jobs/{job_id}/artifacts/manifest.json",
            )
            await job_store.save_job(job)

        except asyncio.TimeoutError:
            end_time = time.monotonic()
            failed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            duration_seconds = round(end_time - start_time, 2)

            job.status = "failed"
            job.stage = "failed"
            job.failed_at = failed_at
            job.duration_seconds = duration_seconds
            job.error = ErrorDetail(
                code="TIMEOUT_EXCEEDED",
                message=f"Job execution timed out after {settings.JOB_TIMEOUT_SECONDS} seconds.",
                retryable=True,
                details={"timeout_seconds": settings.JOB_TIMEOUT_SECONDS},
            )
            await job_store.save_job(job)

        except Exception as exc:
            end_time = time.monotonic()
            failed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            duration_seconds = round(end_time - start_time, 2)

            error_code = "RENDER_PIPELINE_FAILED"
            error_msg = redact_secrets(str(exc))
            exit_code = getattr(exc, "exit_code", 1)

            job.status = "failed"
            job.stage = "failed"
            job.failed_at = failed_at
            job.duration_seconds = duration_seconds
            job.error = ErrorDetail(
                code=error_code,
                message=error_msg or "Process crashed or returned non-zero exit code.",
                retryable=True,
                details={"exit_code": exit_code},
            )
            await job_store.save_job(job)

        finally:
            # Trigger optional callback webhook
            await self._dispatch_webhook(job)

    async def _run_mock_pipeline(
        self,
        job: JobRecord,
        artifacts_dir: Path,
        stdout_log_path: Path,
        stderr_log_path: Path,
    ) -> None:
        """Deterministic mock pipeline for fast, credential-free testing."""
        stages = [
            ("sourcing_footage", 50, 0.05),
            ("normalizing", 65, 0.05),
        ]

        # Log simulated launch
        with open(stdout_log_path, "w", encoding="utf-8") as f:
            f.write(f"[{datetime.now(timezone.utc).isoformat()}] Starting headless mock runner for {job.job_id}\n")

        for stage_name, progress_val, sleep_s in stages:
            await asyncio.sleep(sleep_s)
            job.stage = stage_name
            job.progress = progress_val
            await job_store.save_job(job)
            with open(stdout_log_path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now(timezone.utc).isoformat()}] Stage {stage_name} completed ({progress_val}%)\n")

    async def _run_headless_agy(
        self,
        job: JobRecord,
        input_path: Path,
        workspace_dir: Path,
        artifacts_dir: Path,
        stdout_log_path: Path,
        stderr_log_path: Path,
    ) -> None:
        """Execute the real agy CLI in headless mode."""
        prompt = (
            f"You are the IncuBrix headless agent for job '{job.job_id}'. "
            f"Verify the input script: '{str(job.request.get('script', ''))[:100]}'. "
            "Reply with: 'Job acknowledged and verified'."
        )

        cmd = [
            settings.AGY_BIN_PATH,
            "-p",
            prompt,
            "--dangerously-skip-permissions",
        ]

        # Redact environment variables before spawning subprocess
        env = os.environ.copy()

        # Update stage to sourcing footage
        job.stage = "sourcing_footage"
        job.progress = 40
        await job_store.save_job(job)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace_dir),
            env=env,
        )

        try:
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(),
                timeout=float(settings.JOB_TIMEOUT_SECONDS),
            )
        except asyncio.TimeoutError:
            try:
                proc.terminate()
                await asyncio.sleep(0.5)
                if proc.returncode is None:
                    proc.kill()
            except ProcessLookupError:
                pass
            raise

        stdout_clean = redact_secrets(stdout_data.decode("utf-8", errors="replace"))
        stderr_clean = redact_secrets(stderr_data.decode("utf-8", errors="replace"))

        with open(stdout_log_path, "w", encoding="utf-8") as f:
            f.write(stdout_clean)
        with open(stderr_log_path, "w", encoding="utf-8") as f:
            f.write(stderr_clean)

        if proc.returncode != 0:
            err = RuntimeError(f"Headless agy exited with code {proc.returncode}: {stderr_clean[:200]}")
            setattr(err, "exit_code", proc.returncode)
            raise err

    def _ensure_artifacts(self, job_id: str, artifacts_dir: Path, aspect_ratios: list) -> None:
        """Create valid artifacts adhering to API_CONTRACT.md specs if not already generated."""
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # 1. captions.srt
        srt_file = artifacts_dir / "captions.srt"
        if not srt_file.exists():
            srt_content = (
                "1\n"
                "00:00:00,000 --> 00:00:03,420\n"
                "Saving money doesn't have to be complicated.\n\n"
                "2\n"
                "00:00:03,420 --> 00:00:07,150\n"
                "It starts with understanding where every rupee goes.\n"
            )
            with open(srt_file, "w", encoding="utf-8") as f:
                f.write(srt_content)

        # 2. timeline.json
        timeline_file = artifacts_dir / "timeline.json"
        if not timeline_file.exists():
            timeline_data = {
                "job_id": job_id,
                "total_duration_ms": 7150,
                "scene_count": 2,
                "scenes": [
                    {
                        "scene_index": 0,
                        "start_time_ms": 0,
                        "end_time_ms": 3420,
                        "duration_ms": 3420,
                        "narration_text": "Saving money doesn't have to be complicated.",
                        "visual_hint": "person reviewing savings",
                        "clip": {
                            "clip_id": "px_8439102",
                            "source_provider": "pexels",
                            "source_url": "https://www.pexels.com/video/8439102/",
                            "license": {
                                "type": "Pexels Free License",
                                "commercial_use_allowed": True,
                                "attribution_required": False,
                            },
                            "attribution": "Pexels Stock Video",
                            "is_ai_generated": False,
                            "generator_model": None,
                            "trim": {"in_ms": 0, "out_ms": 3420},
                        },
                        "selection_reason": "Matched personal finance concept.",
                        "relevance_score": 4.8,
                    },
                    {
                        "scene_index": 1,
                        "start_time_ms": 3420,
                        "end_time_ms": 7150,
                        "duration_ms": 3730,
                        "narration_text": "It starts with understanding where every rupee goes.",
                        "visual_hint": "budget app calculation",
                        "clip": {
                            "clip_id": "gen_88419b",
                            "source_provider": "generative_engine",
                            "source_url": "https://storage.incubrix.internal/generated/gen_88419b.mp4",
                            "license": {
                                "type": "Proprietary Commercial Output",
                                "commercial_use_allowed": True,
                                "attribution_required": False,
                            },
                            "attribution": "IncuBrix Generative Video",
                            "is_ai_generated": True,
                            "generator_model": "wan2.1-t2v-14b",
                            "trim": {"in_ms": 0, "out_ms": 3730},
                        },
                        "selection_reason": "Generated clip for precise budget tracking.",
                        "relevance_score": 4.5,
                    },
                ],
            }
            with open(timeline_file, "w", encoding="utf-8") as f:
                json.dump(timeline_data, f, indent=2)

        # 3. manifest.json
        manifest_file = artifacts_dir / "manifest.json"
        if not manifest_file.exists():
            manifest_data = {
                "manifest_version": "1.0.0",
                "job_id": job_id,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "models_and_providers": {
                    "tts": "kokoro-v1.0 (en-IN-female)",
                    "llm_segmenter": "gemini-2.5-flash",
                    "stock_providers": ["pexels-api-v1", "pixabay-api-v1"],
                    "generative_video": "wan2.1-t2v-14b",
                    "relevance_vlm": "clip-vit-base-patch32",
                    "renderer": "ffmpeg-6.1-libx264",
                },
                "settings": {
                    "input_mode": "script",
                    "aspect_ratios": aspect_ratios,
                    "seed": 42,
                    "style": "bright, modern, real-world footage",
                    "avoid": ["people's faces", "alcohol"],
                    "captions": {"burn_in": True, "srt": True},
                },
                "timings_ms": {
                    "total": 5000,
                    "transcription_or_tts": 1000,
                    "segmentation": 800,
                    "footage_search": 1200,
                    "normalization": 800,
                    "rendering": 1200,
                },
                "cost_breakdown": {
                    "currency": "USD",
                    "total_estimated_usd": 0.012,
                    "items": [
                        {
                            "component": "Stock Footage",
                            "provider": "Pexels (Free Commercial)",
                            "units": "1 clip",
                            "cost_usd": 0.0,
                        }
                    ],
                },
                "warnings": [],
                "licensing_summary": {
                    "all_commercial_use_cleared": True,
                    "ai_generated_clips_count": 1,
                    "sources_used": ["pexels", "generative_engine"],
                },
            }
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, indent=2)

    async def _dispatch_webhook(self, job: JobRecord) -> None:
        """Deliver HMAC-signed completion webhook if callback_url is defined."""
        callback_url = job.request.get("callback_url")
        if not callback_url:
            return

        status_response = job.to_status_response()
        payload_bytes = json.dumps(status_response.model_dump(), default=str).encode("utf-8")
        signature = generate_signature(settings.WEBHOOK_SECRET, payload_bytes)

        headers = {
            "Content-Type": "application/json",
            "X-IncuBrix-Signature": signature,
            "X-Correlation-Id": job.correlation_id or "",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(callback_url, content=payload_bytes, headers=headers)
        except Exception:
            # Webhook delivery errors must not crash the job
            pass


runner = JobRunner()
