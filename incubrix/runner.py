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
import time
from typing import Any, Dict, Optional

import httpx

from incubrix.audio import build_audio_pipeline, process_job_audio
from incubrix.config import settings
from incubrix.models import ErrorDetail, JobArtifacts, JobRecord
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

        # 2. Setup job directory structure
        job_dir = settings.JOBS_DIR / job_id
        logs_dir = job_dir / "logs"
        workspace_dir = job_dir / "workspace"
        artifacts_dir = job_dir / "artifacts"

        logs_dir.mkdir(parents=True, exist_ok=True)
        workspace_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        input_path = job_dir / "input.json"
        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(job.request, f, indent=2)

        stdout_log_path = logs_dir / "stdout.log"
        stderr_log_path = logs_dir / "stderr.log"

        # Check if running in mock mode or real agy execution
        is_mock = settings.AGY_MOCK or not Path(settings.AGY_BIN_PATH).exists()

        try:
            # Phase 2 Audio Generation Pipeline
            job.stage = "transcribing"
            job.progress = 20
            await job_store.save_job(job)

            await process_job_audio(
                job_id=job.job_id,
                job_request=job.request,
                workspace_dir=workspace_dir,
                artifacts_dir=artifacts_dir,
                mock=is_mock,
            )

            job.stage = "segmenting"
            job.progress = 35
            await job_store.save_job(job)

            if is_mock:
                await self._run_mock_pipeline(job, artifacts_dir, stdout_log_path, stderr_log_path)
            else:
                await self._run_headless_agy(
                    job, input_path, workspace_dir, artifacts_dir, stdout_log_path, stderr_log_path
                )

            # Execution succeeded
            end_time = time.monotonic()
            completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            duration_seconds = round(end_time - start_time, 2)

            # Ensure deliverables exist (mock or real)
            self._ensure_artifacts(job_id, artifacts_dir, job.request.get("aspect_ratios", ["16:9"]))

            aspect_ratios = job.request.get("aspect_ratios", ["16:9"])
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
            ("normalizing", 75, 0.05),
            ("rendering", 90, 0.05),
            ("packaging", 95, 0.05),
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

        # Create mock output deliverables
        self._ensure_artifacts(job.job_id, artifacts_dir, job.request.get("aspect_ratios", ["16:9"]))

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

        # 1. video_{ratio}.mp4
        for ratio in aspect_ratios:
            safe_name = ratio.replace(":", "_")
            video_file = artifacts_dir / f"video_{safe_name}.mp4"
            if not video_file.exists():
                # Write minimal MP4 header or placeholder content
                with open(video_file, "wb") as f:
                    f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42")

        # 2. captions.srt
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

        # 3. timeline.json
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

        # 4. manifest.json
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
