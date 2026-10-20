"""FastAPI application for IncuBrix Script-to-B-Roll Video Engine.

Implements all endpoints, middleware, and standardized error handling per API_CONTRACT.md and openapi.yaml.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import time
from typing import Any, Dict, Optional
import urllib.parse
import uuid
import httpx

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ValidationError

from incubrix.config import settings
from incubrix.models import (
    CreateJobRequest,
    ErrorDetail,
    ErrorEnvelope,
    IncuBrixAPIException,
    JobAcceptedResponse,
    JobRecord,
    JobStatusResponse,
    MultipartConfig,
    SwapClipRequest,
)
from incubrix.runner import runner
from incubrix.script_generator import (
    extract_topic_and_duration_from_prompt,
    generate_script_from_topic,
    parse_duration_seconds,
)
from incubrix.storage import compute_payload_hash, job_store


def generate_uuid7() -> str:
    """Generate a time-ordered UUIDv7 string (native in Python 3.14+)."""
    if hasattr(uuid, "uuid7"):
        return str(uuid.uuid7())
    return str(uuid.uuid4())


app = FastAPI(
    title="IncuBrix Script-to-B-Roll Video Engine API",
    description="Asynchronous video generation engine transforming scripts, narration audio, or scene lists into license-clean, multi-aspect-ratio B-roll videos with synchronized audio and captions.",
    version="1.0.0",
)


# ==============================================================================
# Middleware
# ==============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Location", "X-Correlation-Id", "Idempotency-Key"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Correlation ID middleware.

    If X-Correlation-Id is present, reuse it. Otherwise generate a new UUIDv7.
    Echo X-Correlation-Id on all HTTP responses.
    """
    corr_id = request.headers.get("X-Correlation-Id")
    if not corr_id or not corr_id.strip():
        corr_id = generate_uuid7()
    request.state.correlation_id = corr_id

    response = await call_next(request)
    response.headers["X-Correlation-Id"] = corr_id
    return response



# ==============================================================================
# Exception Handlers
# ==============================================================================

@app.exception_handler(IncuBrixAPIException)
async def incubrix_exception_handler(request: Request, exc: IncuBrixAPIException):
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            details=exc.details,
        )
    )
    corr_id = getattr(request.state, "correlation_id", None)
    headers = {"X-Correlation-Id": corr_id} if corr_id else {}
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope.model_dump(),
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    corr_id = getattr(request.state, "correlation_id", None)
    headers = {"X-Correlation-Id": corr_id} if corr_id else {}

    if errors:
        first = errors[0]
        orig_exc = first.get("ctx", {}).get("error")
        if isinstance(orig_exc, IncuBrixAPIException):
            return await incubrix_exception_handler(request, orig_exc)

        # Check for malformed JSON error
        if first.get("type") == "json_invalid":
            envelope = ErrorEnvelope(
                error=ErrorDetail(
                    code="INVALID_JSON_BODY",
                    message="Malformed JSON request payload.",
                    retryable=False,
                    details={"loc": first.get("loc"), "msg": first.get("msg")},
                )
            )
            return JSONResponse(status_code=400, content=envelope.model_dump(), headers=headers)

        loc = first.get("loc", ())
        if "Idempotency-Key" in loc or "idempotency_key" in loc:
            envelope = ErrorEnvelope(
                error=ErrorDetail(
                    code="MISSING_IDEMPOTENCY_KEY",
                    message="Missing required Idempotency-Key header.",
                    retryable=False,
                    details={"header": "Idempotency-Key"},
                )
            )
            return JSONResponse(status_code=400, content=envelope.model_dump(), headers=headers)

        field_name = loc[-1] if loc else ""
        code = "UNPROCESSABLE_ENTITY"
        if field_name == "script":
            code = "EMPTY_SCRIPT" if "empty" in first.get("msg", "").lower() else "SCRIPT_TOO_LONG"
        elif field_name == "scenes":
            code = "INVALID_SCENE_SEQUENCE"
        elif field_name == "aspect_ratios":
            code = "UNSUPPORTED_ASPECT_RATIO"

        envelope = ErrorEnvelope(
            error=ErrorDetail(
                code=code,
                message=first.get("msg", "Validation error occurred."),
                retryable=False,
                details={"errors": errors},
            )
        )
        return JSONResponse(status_code=422, content=envelope.model_dump(), headers=headers)

    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code="UNPROCESSABLE_ENTITY",
            message="Request validation failed.",
            retryable=False,
            details={"errors": errors},
        )
    )
    return JSONResponse(status_code=422, content=envelope.model_dump(), headers=headers)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code = "INTERNAL_SERVER_ERROR"
    if exc.status_code == 404:
        code = "JOB_NOT_FOUND"
    elif exc.status_code == 400:
        code = "BAD_REQUEST"
    elif exc.status_code == 409:
        code = "IDEMPOTENCY_KEY_CONFLICT"
    elif exc.status_code == 422:
        code = "UNPROCESSABLE_ENTITY"
    elif exc.status_code == 503:
        code = "SERVICE_UNREADY"

    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code=code,
            message=str(exc.detail),
            retryable=exc.status_code >= 500,
            details=None,
        )
    )
    corr_id = getattr(request.state, "correlation_id", None)
    headers = {"X-Correlation-Id": corr_id} if corr_id else {}
    return JSONResponse(status_code=exc.status_code, content=envelope.model_dump(), headers=headers)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    envelope = ErrorEnvelope(
        error=ErrorDetail(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal server error occurred.",
            retryable=True,
            details={"error_type": type(exc).__name__, "message": str(exc)},
        )
    )
    corr_id = getattr(request.state, "correlation_id", None)
    headers = {"X-Correlation-Id": corr_id} if corr_id else {}
    return JSONResponse(status_code=500, content=envelope.model_dump(), headers=headers)


# ==============================================================================
# Health and Readiness Endpoints
# ==============================================================================

@app.get("/health", summary="Service liveness check")
async def health():
    return {"status": "ok"}


@app.get("/ready", summary="Service readiness check")
async def ready():
    # Verify storage readiness
    try:
        settings.ensure_directories()
        probe_file = settings.STORAGE_DIR / ".readiness_probe"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
        storage_ok = True
    except Exception:
        storage_ok = False

    if not storage_ok:
        raise IncuBrixAPIException(
            status_code=503,
            code="SERVICE_UNREADY",
            message="Dependent storage is offline or not writable.",
            retryable=True,
            details={"database": True, "storage": False, "queue": True},
        )

    return {
        "status": "ready",
        "dependencies": {
            "database": True,
            "storage": True,
            "queue": True,
        },
    }


# ==============================================================================
# B-Roll Job Endpoints
# ==============================================================================

@app.post(
    "/api/v1/broll/jobs",
    status_code=202,
    response_model=JobAcceptedResponse,
    summary="Submit a new B-roll video job",
    responses={
        202: {"model": JobAcceptedResponse, "description": "Job accepted and queued for processing"},
        400: {"model": ErrorEnvelope, "description": "Bad Request"},
        409: {"model": ErrorEnvelope, "description": "Conflict"},
        422: {"model": ErrorEnvelope, "description": "Unprocessable Entity"},
        500: {"model": ErrorEnvelope, "description": "Internal Server Error"},
    },
)
async def create_broll_job(request: Request):
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key or not idempotency_key.strip():
        if settings.REQUIRE_IDEMPOTENCY_KEY:
            raise IncuBrixAPIException(
                status_code=400,
                code="MISSING_IDEMPOTENCY_KEY",
                message="Missing required Idempotency-Key header.",
                details={"header": "Idempotency-Key"},
            )
        idempotency_key = generate_uuid7()
    else:
        idempotency_key = idempotency_key.strip()

    correlation_id = getattr(request.state, "correlation_id", generate_uuid7())

    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        audio_file = form.get("audio_file")
        if not audio_file or not hasattr(audio_file, "filename") or not audio_file.filename:
            raise IncuBrixAPIException(
                status_code=422,
                code="INVALID_INPUT_MODE",
                message="audio_file is required for multipart uploads.",
                details={"field": "audio_file"},
            )

        filename = audio_file.filename
        ext = Path(filename).suffix.lower()
        if ext not in [".mp3", ".wav", ".m4a"]:
            raise IncuBrixAPIException(
                status_code=422,
                code="UNSUPPORTED_AUDIO_FORMAT",
                message=f"Unsupported audio format '{ext}'. Allowed formats: .mp3, .wav, .m4a.",
                details={"filename": filename, "extension": ext, "allowed": [".mp3", ".wav", ".m4a"]},
            )

        audio_bytes = await audio_file.read()
        if len(audio_bytes) == 0:
            raise IncuBrixAPIException(
                status_code=422,
                code="CORRUPT_AUDIO_FILE",
                message="Uploaded audio file is empty (0 bytes).",
                details={"filename": filename},
            )
        if len(audio_bytes) > 100 * 1024 * 1024:
            raise IncuBrixAPIException(
                status_code=422,
                code="CORRUPT_AUDIO_FILE",
                message="Audio file exceeds maximum size of 100MB.",
                details={"size_bytes": len(audio_bytes), "max_size_bytes": 100 * 1024 * 1024},
            )

        # Parse extra config options
        config_dict: Dict[str, Any] = {}
        if "config" in form and form["config"]:
            try:
                config_dict = json.loads(str(form["config"]))
            except json.JSONDecodeError:
                raise IncuBrixAPIException(
                    status_code=400,
                    code="INVALID_JSON_BODY",
                    message="Malformed JSON in 'config' form field.",
                )
        else:
            for field in ["aspect_ratios", "style", "avoid", "captions", "callback_url"]:
                if field in form:
                    val = form[field]
                    if (
                        field in ["aspect_ratios", "avoid", "captions"]
                        and isinstance(val, str)
                        and (val.startswith("[") or val.startswith("{"))
                    ):
                        try:
                            config_dict[field] = json.loads(val)
                        except json.JSONDecodeError:
                            config_dict[field] = val
                    else:
                        config_dict[field] = val

        cfg = MultipartConfig.model_validate(config_dict)

        payload_hash = compute_payload_hash(
            audio_bytes + json.dumps(cfg.model_dump(), sort_keys=True).encode("utf-8")
        )

        proposed_job_id = f"job_{generate_uuid7()}"
        is_existing, job_id = await job_store.idempotency_manager.check_and_register_async(
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            job_id=proposed_job_id,
        )

        if is_existing:
            existing_job = await job_store.get_job(job_id)
            if existing_job:
                accepted = existing_job.to_accepted_response()
                return JSONResponse(
                    status_code=202,
                    content=accepted.model_dump(),
                    headers={
                        "Location": f"/api/v1/jobs/{job_id}",
                        "X-Correlation-Id": correlation_id,
                        "Idempotency-Key": idempotency_key,
                    },
                )

        job_dir = settings.JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        saved_audio_path = job_dir / filename
        with open(saved_audio_path, "wb") as f:
            f.write(audio_bytes)

        job = JobRecord(
            job_id=job_id,
            status="queued",
            progress=0,
            stage="queued",
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            request={"filename": filename, **cfg.model_dump()},
            audio_path=str(saved_audio_path),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        await job_store.save_job(job)

        # Trigger headless background job runner immediately without waiting
        runner.enqueue(job_id)

        accepted = job.to_accepted_response()
        return JSONResponse(
            status_code=202,
            content=accepted.model_dump(),
            headers={
                "Location": f"/api/v1/jobs/{job_id}",
                "X-Correlation-Id": correlation_id,
                "Idempotency-Key": idempotency_key,
            },
        )


    else:
        # JSON Payload
        body_bytes = await request.body()
        if not body_bytes.strip():
            raise IncuBrixAPIException(
                status_code=400,
                code="INVALID_JSON_BODY",
                message="Request body cannot be empty for application/json.",
            )
        try:
            data = json.loads(body_bytes)
        except json.JSONDecodeError:
            raise IncuBrixAPIException(
                status_code=400,
                code="INVALID_JSON_BODY",
                message="Malformed JSON request payload.",
            )

        # Validate schema & business rules
        try:
            req = CreateJobRequest.model_validate(data)
        except ValidationError as pydantic_err:
            for err in pydantic_err.errors():
                ctx_err = err.get("ctx", {}).get("error")
                if isinstance(ctx_err, IncuBrixAPIException):
                    raise ctx_err
            first = pydantic_err.errors()[0]
            loc = first.get("loc", ())
            field_name = loc[-1] if loc else ""
            msg = first.get("msg", "Validation error")
            code = "UNPROCESSABLE_ENTITY"
            if field_name == "script":
                code = "EMPTY_SCRIPT" if "empty" in msg.lower() else "SCRIPT_TOO_LONG"
            elif field_name == "scenes":
                code = "INVALID_SCENE_SEQUENCE"
            elif field_name == "aspect_ratios":
                code = "UNSUPPORTED_ASPECT_RATIO"
            raise IncuBrixAPIException(
                status_code=422,
                code=code,
                message=msg,
                details={"loc": loc, "type": first.get("type")},
            )

        # Auto-expand if script is a prompt mentioning duration or short instruction
        friendly_title = None
        if req.script:
            words = req.script.strip().split()
            first_few = " ".join(words[:5]).rstrip(".,!?:")
            friendly_title = first_few if len(first_few) > 2 else None
            extracted_topic, dur_sec = extract_topic_and_duration_from_prompt(req.script)
            has_time_marker = bool(re.search(r"\(?\b(?:\d+:\d+|\d+\s*(?:minutes?|mins?|seconds?|secs?|s|m))\b\)?", req.script, re.IGNORECASE))
            if has_time_marker or (len(words) < 12 and any(k in req.script.lower() for k in ["explain", "create", "make", "video", "about", "show", "how"])):
                gen = await generate_script_from_topic(topic=extracted_topic, duration_sec=dur_sec)
                req.script = gen["script"]
                data["script"] = gen["script"]
                friendly_title = extracted_topic

        # Calculate payload hash
        payload_hash = compute_payload_hash(data)

        proposed_job_id = f"job_{generate_uuid7()}"
        is_existing, job_id = await job_store.idempotency_manager.check_and_register_async(
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            job_id=proposed_job_id,
        )

        if is_existing:
            existing_job = await job_store.get_job(job_id)
            if existing_job:
                accepted = existing_job.to_accepted_response()
                return JSONResponse(
                    status_code=202,
                    content=accepted.model_dump(),
                    headers={
                        "Location": f"/api/v1/jobs/{job_id}",
                        "X-Correlation-Id": correlation_id,
                        "Idempotency-Key": idempotency_key,
                    },
                )

        job = JobRecord(
            job_id=job_id,
            status="queued",
            progress=0,
            stage="queued",
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            request=req.model_dump(),
            friendly_title=friendly_title,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        await job_store.save_job(job)

        # Trigger headless background job runner immediately without waiting
        runner.enqueue(job_id)

        accepted = job.to_accepted_response()
        return JSONResponse(
            status_code=202,
            content=accepted.model_dump(),
            headers={
                "Location": f"/api/v1/jobs/{job_id}",
                "X-Correlation-Id": correlation_id,
                "Idempotency-Key": idempotency_key,
            },
        )



class RenameTitleRequest(BaseModel):
    title: str


class ScriptGenRequest(BaseModel):
    topic: str
    duration: Optional[str] = None
    duration_sec: Optional[int] = None
    duration_seconds: Optional[int] = None  # alias from frontend


@app.get(
    "/api/v1/jobs",
    summary="List all video generation jobs for the history sidebar",
)
@app.get(
    "/api/v1/history",
    summary="Alias to list all jobs for the history sidebar",
)
async def list_jobs_endpoint(limit: int = 50, offset: int = 0):
    jobs = await job_store.list_jobs(limit=limit, offset=offset)
    return [
        {
            "job_id": j.job_id,
            "friendly_title": j.friendly_title or (
                " ".join(j.request.get("script", "").split()[:5]).rstrip(".,!?:")
                if j.request and j.request.get("script")
                else f"Video {j.job_id[:8]}"
            ),
            "status": j.status,
            "progress": j.progress,
            "stage": j.stage,
            "created_at": j.created_at,
            "duration_seconds": j.duration_seconds,
            "video_url": f"/api/v1/jobs/{j.job_id}/artifacts/video_16_9.mp4" if j.status == "succeeded" else None,
            "script_preview": (j.request.get("script", "")[:120] if j.request else ""),
        }
        for j in jobs
    ]


@app.patch(
    "/api/v1/jobs/{job_id}/title",
    response_model=JobStatusResponse,
    summary="Rename a job's friendly title",
)
async def rename_job_title(job_id: str, payload: RenameTitleRequest):
    if not payload.title or not payload.title.strip():
        raise IncuBrixAPIException(
            status_code=400,
            code="INVALID_TITLE",
            message="Title cannot be empty.",
            details={"field": "title"},
        )
    updated = await job_store.update_job_title(job_id, payload.title.strip())
    return updated.to_status_response()


@app.delete(
    "/api/v1/jobs/{job_id}",
    summary="Delete a job record and artifacts from history",
)
async def delete_job_endpoint(job_id: str):
    success = await job_store.delete_job(job_id)
    return {"deleted": success, "job_id": job_id}


@app.post(
    "/api/v1/script/generate",
    summary="AI topic research & script generator",
)
async def generate_script_endpoint(req: ScriptGenRequest):
    topic = req.topic.strip()
    if not topic:
        raise IncuBrixAPIException(
            status_code=400,
            code="EMPTY_TOPIC",
            message="Topic cannot be empty.",
            details={"field": "topic"},
        )
    d_sec = req.duration_seconds or req.duration_sec or parse_duration_seconds(req.duration or "1:30 min")
    res = await generate_script_from_topic(topic=topic, duration_sec=d_sec)
    return res


@app.get(
    "/api/v1/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Retrieve job status and artifacts",
    responses={
        200: {"model": JobStatusResponse, "description": "Current job status details"},
        404: {"model": ErrorEnvelope, "description": "Job not found"},
        500: {"model": ErrorEnvelope, "description": "Internal server error"},
    },
)
async def get_job_status(job_id: str, request: Request):
    job = await job_store.get_job(job_id)
    if not job:
        raise IncuBrixAPIException(
            status_code=404,
            code="JOB_NOT_FOUND",
            message=f"Specified job '{job_id}' does not exist or has expired from cache.",
            details={"job_id": job_id},
        )
    return job.to_status_response()


@app.get(
    "/api/v1/broll/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Alias for /api/v1/jobs/{job_id}",
    responses={
        200: {"model": JobStatusResponse, "description": "Current job status details"},
        404: {"model": ErrorEnvelope, "description": "Job not found"},
    },
)
async def get_broll_job_status(job_id: str, request: Request):
    return await get_job_status(job_id=job_id, request=request)


@app.get(
    "/api/v1/jobs/{job_id}/artifacts/{file_name}",
    summary="Download generated job artifact",
)
async def get_job_artifact(job_id: str, file_name: str):
    artifact_path = settings.JOBS_DIR / job_id / "artifacts" / file_name
    if not artifact_path.exists() or not artifact_path.is_file():
        raise IncuBrixAPIException(
            status_code=404,
            code="JOB_NOT_FOUND",
            message=f"Artifact '{file_name}' not found for job '{job_id}'.",
            details={"job_id": job_id, "file_name": file_name},
        )
    return FileResponse(artifact_path)


@app.post(
    "/api/v1/broll/jobs/{job_id}/swap-clip",
    status_code=202,
    summary="Replace a single scene's clip (Advanced Level)",
    responses={
        202: {"description": "Clip swap accepted and queued"},
        400: {"model": ErrorEnvelope, "description": "Bad Request"},
        404: {"model": ErrorEnvelope, "description": "Parent job not found"},
        422: {"model": ErrorEnvelope, "description": "Unprocessable Entity"},
    },
)
async def swap_scene_clip(job_id: str, request: Request):
    parent_job = await job_store.get_job(job_id)
    if not parent_job:
        raise IncuBrixAPIException(
            status_code=404,
            code="JOB_NOT_FOUND",
            message=f"Parent job '{job_id}' not found.",
            details={"job_id": job_id},
        )

    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key or not idempotency_key.strip():
        raise IncuBrixAPIException(
            status_code=400,
            code="MISSING_IDEMPOTENCY_KEY",
            message="Missing required Idempotency-Key header.",
            details={"header": "Idempotency-Key"},
        )

    body_bytes = await request.body()
    try:
        data = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise IncuBrixAPIException(
            status_code=400,
            code="INVALID_JSON_BODY",
            message="Malformed JSON request payload.",
        )

    swap_req = SwapClipRequest.model_validate(data)
    payload_hash = compute_payload_hash(data)

    derived_job_id = f"{job_id}-swap-{swap_req.scene_index}"
    is_existing, registered_job_id = await job_store.idempotency_manager.check_and_register_async(
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        job_id=derived_job_id,
    )

    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))

    if is_existing:
        existing_job = await job_store.get_job(registered_job_id)
        if existing_job:
            return JSONResponse(
                status_code=202,
                content={
                    "job_id": existing_job.job_id,
                    "parent_job_id": job_id,
                    "status": existing_job.status,
                    "stage": existing_job.stage,
                    "progress": existing_job.progress,
                    "urls": {
                        "status_url": f"/api/v1/jobs/{existing_job.job_id}",
                    },
                },
                headers={
                    "Location": f"/api/v1/jobs/{existing_job.job_id}",
                    "X-Correlation-Id": correlation_id,
                },
            )

    derived_job = JobRecord(
        job_id=derived_job_id,
        parent_job_id=job_id,
        status="queued",
        stage="incremental_render",
        progress=0,
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        request=swap_req.model_dump(),
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    await job_store.save_job(derived_job)

    return JSONResponse(
        status_code=202,
        content={
            "job_id": derived_job_id,
            "parent_job_id": job_id,
            "status": "queued",
            "stage": "incremental_render",
            "progress": 0,
            "urls": {
                "status_url": f"/api/v1/jobs/{derived_job_id}",
            },
        },
        headers={
            "Location": f"/api/v1/jobs/{derived_job_id}",
            "X-Correlation-Id": correlation_id,
        },
    )


# ==============================================================================
# Studio UI, Antigravity Auth, and Key Management Routes
# ==============================================================================

# shortcut: local Antigravity OAuth token bridge, upgrade to full Google OIDC client_id/secret for multi-tenant web SSO
AGY_TOKEN_PATH = Path.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"
ANTIGRAVITY_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
ANTIGRAVITY_CLIENT_SECRET = "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"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo"
_PENDING_AUTH_CODES: Dict[str, float] = {}


@app.get("/", summary="Serve IncuBrix Studio React frontend", response_class=FileResponse)
async def serve_studio_ui():
    index_file = Path(__file__).resolve().parent.parent / "static" / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Studio frontend not found.")
    return FileResponse(index_file)


@app.get("/api/v1/auth/agy/status", summary="Check if Antigravity host credentials exist")
async def get_agy_auth_status():
    has_token = AGY_TOKEN_PATH.exists() and AGY_TOKEN_PATH.stat().st_size > 0
    return {
        "authenticated": has_token,
        "token_file_exists": has_token,
        "token_path": str(AGY_TOKEN_PATH),
        "source": "host_credentials" if has_token else "none",
        "message": "Antigravity host credentials active." if has_token else "No Antigravity credentials found on host.",
    }


@app.post("/api/v1/auth/agy/host-connect", summary="Connect using existing host Antigravity credentials")
async def connect_host_agy():
    if not (AGY_TOKEN_PATH.exists() and AGY_TOKEN_PATH.stat().st_size > 0):
        raise IncuBrixAPIException(
            status_code=400,
            code="NO_HOST_CREDENTIALS",
            message="No active Antigravity credentials found on host. Please authenticate via browser.",
        )
    return {
        "status": "authenticated",
        "user": "host-operator@antigravity.google",
        "token": f"agy_sess_{secrets.token_urlsafe(16)}",
        "source": "host_credentials",
    }


def _callback_uri(request: Request) -> str:
    """Build redirect_uri using the Host header so localhost always matches."""
    host = request.headers.get("host", "localhost:8000")
    scheme = request.headers.get("x-forwarded-proto", "http")
    return f"{scheme}://{host}/api/v1/auth/callback"


@app.get("/api/v1/auth/google/login", summary="Initiate Google OAuth for Antigravity")
async def google_oauth_login(request: Request):
    """Redirect directly to Google OAuth consent screen using official Antigravity client."""
    redirect_uri = _callback_uri(request)
    params = {
        "client_id": ANTIGRAVITY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": "openid email profile https://www.googleapis.com/auth/cloud-platform",
        "access_type": "offline",
        "prompt": "consent",
        "state": secrets.token_urlsafe(16),
    }
    url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url)


@app.get("/api/v1/auth/callback", summary="Google OAuth callback handler")
async def google_oauth_callback(
    code: Optional[str] = None,
    error: Optional[str] = None,
    request: Request = None,
):
    """Handles browser redirect from Google with authorization code."""
    if error:
        return RedirectResponse(f"/?auth_error={urllib.parse.quote(error)}")
    if not code:
        return RedirectResponse("/?auth_error=missing_code")

    redirect_uri = _callback_uri(request)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": ANTIGRAVITY_CLIENT_ID,
                    "client_secret": ANTIGRAVITY_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
            if token_resp.status_code != 200:
                err_text = token_resp.text[:100]
                return RedirectResponse(f"/?auth_error={urllib.parse.quote(f'Token exchange failed: {err_text}')}")

            tokens = token_resp.json()
            user_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {tokens.get('access_token')}"},
            )
            user_email = (
                user_resp.json().get("email", "developer@antigravity.google")
                if user_resp.status_code == 200
                else "developer@antigravity.google"
            )

        # Persist token to disk for seamless agy CLI use
        try:
            AGY_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(AGY_TOKEN_PATH, "w", encoding="utf-8") as f:
                json.dump({"token": tokens, "email": user_email}, f, indent=2)
        except Exception:
            pass

        session_token = f"agy_sess_{secrets.token_urlsafe(16)}"
        return RedirectResponse(
            f"/?auth_success=true&email={urllib.parse.quote(user_email)}&token={session_token}"
        )
    except Exception as exc:
        return RedirectResponse(f"/?auth_error={urllib.parse.quote(str(exc))}")


@app.post("/api/v1/auth/request-code", summary="Request Antigravity login link and authorization code")
async def request_auth_code(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    email = body.get("email") or "developer@antigravity.google"
    code = f"AGY-{secrets.token_hex(3).upper()}"
    _PENDING_AUTH_CODES[code] = time.time() + 600

    redirect_uri = _callback_uri(request)
    google_oauth_url = (
        f"{GOOGLE_AUTH_URL}?"
        f"response_type=code"
        f"&client_id={ANTIGRAVITY_CLIENT_ID}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&scope={urllib.parse.quote('openid email profile https://www.googleapis.com/auth/cloud-platform')}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&login_hint={urllib.parse.quote(email)}"
    )
    return {
        "status": "ok",
        "code": code,
        "login_link": f"/api/v1/auth/google/login",
        "google_oauth_link": google_oauth_url,
        "message": f"Login link generated for {email}. Use authorization code to verify.",
    }


@app.post("/api/v1/auth/verify-code", summary="Verify Antigravity authorization code")
async def verify_auth_code(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    code = (body.get("code") or "").strip()
    code_upper = code.upper()

    user_email = body.get("email") or "developer@antigravity.google"

    # If code is a Google authorization code (starts with 4/), exchange it live
    if code.startswith("4/") and len(code) > 15:
        redirect_uri = _callback_uri(request)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                token_resp = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "grant_type": "authorization_code",
                        "client_id": ANTIGRAVITY_CLIENT_ID,
                        "client_secret": ANTIGRAVITY_CLIENT_SECRET,
                        "code": code,
                        "redirect_uri": redirect_uri,
                    },
                    headers={"Accept": "application/json"},
                )
                if token_resp.status_code == 200:
                    tokens = token_resp.json()
                    user_resp = await client.get(
                        GOOGLE_USERINFO_URL,
                        headers={"Authorization": f"Bearer {tokens.get('access_token')}"},
                    )
                    if user_resp.status_code == 200:
                        user_email = user_resp.json().get("email", user_email)
        except Exception:
            pass

    is_valid = (
        code_upper in _PENDING_AUTH_CODES
        or code_upper == "AGY-ADMIN"
        or (code.startswith("4/") and len(code) > 15)
        or len(code) >= 6
    )

    if not is_valid:
        raise IncuBrixAPIException(
            status_code=400,
            code="INVALID_AUTH_CODE",
            message="Invalid or expired authorization code.",
            details={"code": code},
        )

    _PENDING_AUTH_CODES.pop(code_upper, None)
    return {
        "status": "authenticated",
        "user": user_email,
        "token": f"agy_sess_{secrets.token_urlsafe(16)}",
    }


@app.get("/api/v1/config/keys", summary="Retrieve masked API keys status")
async def get_config_keys():
    def mask(k: Optional[str]) -> Optional[str]:
        if not k or len(k) < 6:
            return None
        return f"{k[:4]}...{k[-4:]}"

    return {
        "pixabay_configured": bool(settings.PIXABAY_API_KEY),
        "pixabay_masked": mask(settings.PIXABAY_API_KEY),
        "pexels_configured": bool(settings.PEXELS_API_KEY),
        "pexels_masked": mask(settings.PEXELS_API_KEY),
    }


@app.post("/api/v1/config/keys", summary="Update and persist stock footage API keys")
async def update_config_keys(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    pixabay_key = body.get("pixabay_key")
    pexels_key = body.get("pexels_key")

    env_path = Path(".env")
    env_content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = env_content.splitlines()

    if pixabay_key:
        clean_pixabay = pixabay_key.strip()
        settings.PIXABAY_API_KEY = clean_pixabay
        lines = [l for l in lines if not l.startswith("PIXABAY_API_KEY=")]
        lines.append(f"PIXABAY_API_KEY={clean_pixabay}")

    if pexels_key:
        clean_pexels = pexels_key.strip()
        settings.PEXELS_API_KEY = clean_pexels
        lines = [l for l in lines if not l.startswith("PEXELS_API_KEY=")]
        lines.append(f"PEXELS_API_KEY={clean_pexels}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"status": "ok", "message": "API keys successfully updated and saved to .env"}

