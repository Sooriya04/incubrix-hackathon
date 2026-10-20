"""Pydantic models and exception definitions for IncuBrix Script-to-B-Roll Video Engine.

Strictly aligned with API_CONTRACT.md and openapi.yaml specifications.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator


# ==============================================================================
# Exceptions
# ==============================================================================

class IncuBrixAPIException(ValueError):
    """Custom API Exception mapped directly to standardized IncuBrix error envelopes."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details
        super().__init__(message)


# ==============================================================================
# Error Models
# ==============================================================================

class ErrorDetail(BaseModel):
    code: str = Field(..., description="Canonical UPPER_SNAKE_CASE error code.")
    message: str = Field(..., description="Human readable explanation of the failure.")
    retryable: bool = Field(default=False, description="Whether the request is safely retryable.")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Granular troubleshooting context.")


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


# ==============================================================================
# Request Component Models
# ==============================================================================

class CaptionSettings(BaseModel):
    burn_in: bool = Field(default=True, description="Whether to burn subtitles directly into video.")
    srt: bool = Field(default=True, description="Whether to export an independent .srt subtitle file.")


class SceneInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000, description="Spoken narration for this scene.")
    visual_hint: Optional[str] = Field(default=None, max_length=300, description="Visual cue for clip matching.")

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise IncuBrixAPIException(
                status_code=422,
                code="EMPTY_SCRIPT",
                message="Scene text cannot be empty or whitespace only.",
            )
        return v


# ==============================================================================
# Job Creation Request Models
# ==============================================================================

SUPPORTED_ASPECT_RATIOS = {"16:9", "9:16", "1:1"}


class CreateJobRequest(BaseModel):
    script: Optional[str] = None
    audio_url: Optional[str] = None
    scenes: Optional[List[SceneInput]] = None
    voice: Optional[str] = Field(default="en-IN-female")
    aspect_ratios: List[str] = Field(default_factory=lambda: ["16:9"])
    style: Optional[str] = Field(default="bright, modern, real-world footage")
    avoid: List[str] = Field(default_factory=list)
    captions: CaptionSettings = Field(default_factory=CaptionSettings)
    callback_url: Optional[str] = None
    duration_seconds: Optional[int] = Field(
        default=None,
        ge=5,
        le=600,
        description="Requested finished-video duration. Narration is fitted to this duration when supplied.",
    )

    @model_validator(mode="before")
    @classmethod
    def validate_request_payload(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        # Check script validations
        has_script = "script" in data and data["script"] is not None
        if has_script:
            val = data["script"]
            if not isinstance(val, str) or not val.strip():
                raise IncuBrixAPIException(
                    status_code=422,
                    code="EMPTY_SCRIPT",
                    message="Script cannot be empty or whitespace only.",
                    details={"field": "script", "issue": "empty_or_whitespace"},
                )
            if len(val) > 15000:
                raise IncuBrixAPIException(
                    status_code=422,
                    code="SCRIPT_TOO_LONG",
                    message="Script exceeds maximum allowed length of 15000 characters.",
                    details={"field": "script", "length": len(val), "max_length": 15000},
                )

        # Check scenes validations
        has_scenes = "scenes" in data and data["scenes"] is not None
        if has_scenes:
            scenes = data["scenes"]
            if not isinstance(scenes, list) or len(scenes) == 0 or len(scenes) > 100:
                raise IncuBrixAPIException(
                    status_code=422,
                    code="INVALID_SCENE_SEQUENCE",
                    message="Scenes list must contain between 1 and 100 items.",
                    details={"field": "scenes", "count": len(scenes) if isinstance(scenes, list) else 0},
                )
            for idx, item in enumerate(scenes):
                if not isinstance(item, dict):
                    raise IncuBrixAPIException(
                        status_code=422,
                        code="INVALID_SCENE_SEQUENCE",
                        message="Each item in scenes must be an object with 'text' field.",
                        details={"field": f"scenes[{idx}]"},
                    )
                txt = item.get("text")
                if txt is None or not isinstance(txt, str) or not txt.strip():
                    raise IncuBrixAPIException(
                        status_code=422,
                        code="EMPTY_SCRIPT",
                        message=f"Scene {idx} narration text cannot be empty or whitespace only.",
                        details={"scene_index": idx, "field": f"scenes[{idx}].text"},
                    )
                if len(txt) > 1000:
                    raise IncuBrixAPIException(
                        status_code=422,
                        code="SCRIPT_TOO_LONG",
                        message=f"Scene {idx} narration text exceeds maximum length of 1000 characters.",
                        details={"scene_index": idx, "field": f"scenes[{idx}].text", "length": len(txt)},
                    )

        # Check audio_url validations
        has_audio = "audio_url" in data and data["audio_url"] is not None
        if has_audio:
            url = data["audio_url"]
            if not isinstance(url, str) or not url.strip() or not (url.startswith("http://") or url.startswith("https://")):
                raise IncuBrixAPIException(
                    status_code=422,
                    code="AUDIO_DOWNLOAD_FAILED",
                    message="Audio URL must be a valid HTTP or HTTPS URL.",
                    details={"field": "audio_url", "value": url},
                )

        # Primary Input Mode Strict XOR
        modes_count = sum(1 for m in [has_script, has_audio, has_scenes] if m)
        if modes_count != 1:
            raise IncuBrixAPIException(
                status_code=422,
                code="INVALID_INPUT_MODE",
                message="Exactly one primary input mode must be specified: script, audio_url, or scenes.",
                details={
                    "has_script": has_script,
                    "has_audio_url": has_audio,
                    "has_scenes": has_scenes,
                },
            )

        # Aspect ratios validation
        if "aspect_ratios" in data and data["aspect_ratios"] is not None:
            ratios = data["aspect_ratios"]
            if not isinstance(ratios, list) or len(ratios) == 0:
                raise IncuBrixAPIException(
                    status_code=422,
                    code="UNSUPPORTED_ASPECT_RATIO",
                    message="aspect_ratios must be a non-empty list of supported ratios.",
                    details={"field": "aspect_ratios", "allowed": sorted(list(SUPPORTED_ASPECT_RATIOS))},
                )
            for r in ratios:
                if r not in SUPPORTED_ASPECT_RATIOS:
                    raise IncuBrixAPIException(
                        status_code=422,
                        code="UNSUPPORTED_ASPECT_RATIO",
                        message=f"Unsupported aspect ratio '{r}'. Allowed values: {sorted(list(SUPPORTED_ASPECT_RATIOS))}.",
                        details={"field": "aspect_ratios", "invalid_ratio": r, "allowed": sorted(list(SUPPORTED_ASPECT_RATIOS))},
                    )
            # Deduplicate while preserving order
            data["aspect_ratios"] = list(dict.fromkeys(ratios))

        # Style length check
        if "style" in data and data["style"] is not None:
            st = data["style"]
            if isinstance(st, str) and len(st) > 300:
                raise IncuBrixAPIException(
                    status_code=422,
                    code="INVALID_REQUEST",
                    message="Style guidance cannot exceed 300 characters.",
                    details={"field": "style", "length": len(st), "max_length": 300},
                )

        # Avoid list validation
        if "avoid" in data and data["avoid"] is not None:
            av = data["avoid"]
            if not isinstance(av, list):
                raise IncuBrixAPIException(
                    status_code=422,
                    code="INVALID_REQUEST",
                    message="avoid must be a list of string constraints.",
                    details={"field": "avoid"},
                )
            if len(av) > 20:
                raise IncuBrixAPIException(
                    status_code=422,
                    code="INVALID_REQUEST",
                    message="Avoid list cannot exceed 20 items.",
                    details={"field": "avoid", "count": len(av), "max_items": 20},
                )
            for idx, item in enumerate(av):
                if not isinstance(item, str) or len(item) > 100:
                    raise IncuBrixAPIException(
                        status_code=422,
                        code="INVALID_REQUEST",
                        message=f"Avoid item at index {idx} exceeds maximum length of 100 characters.",
                        details={"field": f"avoid[{idx}]", "length": len(str(item)), "max_length": 100},
                    )

        return data


class MultipartConfig(BaseModel):
    aspect_ratios: List[str] = Field(default_factory=lambda: ["16:9"])
    style: Optional[str] = Field(default="bright, modern, real-world footage")
    avoid: List[str] = Field(default_factory=list)
    captions: CaptionSettings = Field(default_factory=CaptionSettings)
    callback_url: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def validate_multipart_config(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        if "aspect_ratios" in data and data["aspect_ratios"] is not None:
            ratios = data["aspect_ratios"]
            if isinstance(ratios, str):
                ratios = [r.strip() for r in ratios.split(",") if r.strip()]
            if not isinstance(ratios, list) or len(ratios) == 0:
                raise IncuBrixAPIException(
                    status_code=422,
                    code="UNSUPPORTED_ASPECT_RATIO",
                    message="aspect_ratios must be a non-empty list of supported ratios.",
                    details={"field": "aspect_ratios", "allowed": sorted(list(SUPPORTED_ASPECT_RATIOS))},
                )
            for r in ratios:
                if r not in SUPPORTED_ASPECT_RATIOS:
                    raise IncuBrixAPIException(
                        status_code=422,
                        code="UNSUPPORTED_ASPECT_RATIO",
                        message=f"Unsupported aspect ratio '{r}'. Allowed values: {sorted(list(SUPPORTED_ASPECT_RATIOS))}.",
                        details={"field": "aspect_ratios", "invalid_ratio": r, "allowed": sorted(list(SUPPORTED_ASPECT_RATIOS))},
                    )
            data["aspect_ratios"] = list(dict.fromkeys(ratios))

        if "style" in data and data["style"] is not None:
            st = data["style"]
            if isinstance(st, str) and len(st) > 300:
                raise IncuBrixAPIException(
                    status_code=422,
                    code="INVALID_REQUEST",
                    message="Style guidance cannot exceed 300 characters.",
                    details={"field": "style", "length": len(st), "max_length": 300},
                )

        if "avoid" in data and data["avoid"] is not None:
            av = data["avoid"]
            if isinstance(av, str):
                av = [a.strip() for a in av.split(",") if a.strip()]
            if len(av) > 20:
                raise IncuBrixAPIException(
                    status_code=422,
                    code="INVALID_REQUEST",
                    message="Avoid list cannot exceed 20 items.",
                    details={"field": "avoid", "count": len(av), "max_items": 20},
                )
            for idx, item in enumerate(av):
                if not isinstance(item, str) or len(item) > 100:
                    raise IncuBrixAPIException(
                        status_code=422,
                        code="INVALID_REQUEST",
                        message=f"Avoid item at index {idx} exceeds maximum length of 100 characters.",
                        details={"field": f"avoid[{idx}]"},
                    )
            data["avoid"] = av

        return data


class SwapClipRequest(BaseModel):
    scene_index: int = Field(..., ge=0, description="0-indexed scene to modify.")
    replacement_clip_url: str = Field(..., description="Source URL of replacement footage clip.")
    visual_hint: Optional[str] = Field(default=None, description="Visual description or hint.")
    selection_reason: Optional[str] = Field(default=None, description="Reason for replacement.")


# ==============================================================================
# Response & Artifact Models
# ==============================================================================

class JobUrls(BaseModel):
    status_url: str = Field(..., json_schema_extra={"example": "/api/v1/jobs/job_9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"})
    cancel_url: Optional[str] = Field(
        default=None,
        json_schema_extra={"example": "/api/v1/jobs/job_9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d/cancel"},
    )


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: str = Field(default="queued")
    progress: int = Field(default=0)
    stage: str = Field(default="queued")
    created_at: str
    urls: JobUrls
    idempotency_key: Optional[str] = None


class JobArtifacts(BaseModel):
    videos: Dict[str, str] = Field(
        ...,
        description="Map of aspect ratio ('16:9', '9:16', '1:1') to download URL.",
    )
    captions: str = Field(..., description="Download URL for captions.srt.")
    timeline: str = Field(..., description="Download URL for timeline.json.")
    manifest: str = Field(..., description="Download URL for manifest.json.")


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    progress: int = Field(..., ge=0, le=100)
    stage: Literal[
        "queued",
        "transcribing",
        "segmenting",
        "sourcing_footage",
        "normalizing",
        "rendering",
        "packaging",
        "completed",
        "failed",
        "incremental_render",
    ]
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    failed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    estimated_remaining_seconds: Optional[int] = None
    error: Optional[ErrorDetail] = None
    artifacts: Optional[JobArtifacts] = None
    friendly_title: Optional[str] = None
    request: Optional[Dict[str, Any]] = None


# ==============================================================================
# Persistent Job Storage Record
# ==============================================================================

class JobRecord(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"] = "queued"
    progress: int = 0
    stage: Literal[
        "queued",
        "transcribing",
        "segmenting",
        "sourcing_footage",
        "normalizing",
        "rendering",
        "packaging",
        "completed",
        "failed",
        "incremental_render",
    ] = "queued"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    failed_at: Optional[str] = None
    duration_seconds: Optional[float] = None
    estimated_remaining_seconds: Optional[int] = None
    error: Optional[ErrorDetail] = None
    artifacts: Optional[JobArtifacts] = None
    friendly_title: Optional[str] = None

    # Internal job attributes
    request: Optional[Dict[str, Any]] = None
    audio_path: Optional[str] = None
    idempotency_key: Optional[str] = None
    correlation_id: Optional[str] = None
    parent_job_id: Optional[str] = None

    def to_accepted_response(self) -> JobAcceptedResponse:
        return JobAcceptedResponse(
            job_id=self.job_id,
            status=self.status,
            progress=self.progress,
            stage=self.stage,
            created_at=self.created_at,
            urls=JobUrls(
                status_url=f"/api/v1/jobs/{self.job_id}",
                cancel_url=f"/api/v1/jobs/{self.job_id}/cancel",
            ),
            idempotency_key=self.idempotency_key,
        )

    def to_status_response(self) -> JobStatusResponse:
        return JobStatusResponse(
            job_id=self.job_id,
            status=self.status,
            progress=self.progress,
            stage=self.stage,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            failed_at=self.failed_at,
            duration_seconds=self.duration_seconds,
            estimated_remaining_seconds=self.estimated_remaining_seconds,
            error=self.error,
            artifacts=self.artifacts,
            friendly_title=self.friendly_title,
            request=self.request,
        )
