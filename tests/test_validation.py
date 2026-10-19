"""Test request validation and error envelope adhering to API_CONTRACT.md."""

import pytest
import httpx


@pytest.mark.asyncio
async def test_health_and_ready(client: httpx.AsyncClient):
    """Liveness and readiness endpoints."""
    res_health = await client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json() == {"status": "ok"}

    res_ready = await client.get("/ready")
    assert res_ready.status_code == 200
    ready_body = res_ready.json()
    assert ready_body["status"] == "ready"
    assert ready_body["dependencies"]["database"] is True
    assert ready_body["dependencies"]["storage"] is True
    assert ready_body["dependencies"]["queue"] is True


@pytest.mark.asyncio
async def test_missing_idempotency_key_in_strict_mode(client: httpx.AsyncClient, monkeypatch):
    """POST without Idempotency-Key returns 400 MISSING_IDEMPOTENCY_KEY when strict mode is on."""
    from incubrix.config import settings

    monkeypatch.setattr(settings, "REQUIRE_IDEMPOTENCY_KEY", True)
    payload = {"script": "Valid narration text"}
    res = await client.post("/api/v1/broll/jobs", json=payload)
    assert res.status_code == 400
    body = res.json()
    assert "error" in body
    assert body["error"]["code"] == "MISSING_IDEMPOTENCY_KEY"
    assert body["error"]["retryable"] is False


@pytest.mark.asyncio
async def test_auto_generated_uuid7_idempotency_key(client: httpx.AsyncClient):
    """When Idempotency-Key header is omitted, auto-generate a UUIDv7 and return in headers."""
    payload = {"script": "Valid narration text without explicit idempotency key"}
    res = await client.post("/api/v1/broll/jobs", json=payload)
    assert res.status_code == 202
    assert "Idempotency-Key" in res.headers
    generated_key = res.headers["Idempotency-Key"]
    assert len(generated_key) == 36
    # Verify version 7 in UUID hex (character 14 is '7' for UUIDv7, e.g. 01a154cf-844a-733c-...)
    assert generated_key[14] == "7"
    body = res.json()
    assert body["idempotency_key"] == generated_key


@pytest.mark.asyncio
async def test_invalid_json_body(client: httpx.AsyncClient):
    """POST with malformed JSON body returns 400 INVALID_JSON_BODY."""
    headers = {"Idempotency-Key": "test-key-invalid-json", "Content-Type": "application/json"}
    res = await client.post("/api/v1/broll/jobs", content=b"invalid { json", headers=headers)
    assert res.status_code == 400
    body = res.json()
    assert body["error"]["code"] == "INVALID_JSON_BODY"


@pytest.mark.asyncio
async def test_strict_xor_primary_input_mode_none(client: httpx.AsyncClient):
    """POST with none of script, audio_url, or scenes returns 422 INVALID_INPUT_MODE."""
    headers = {"Idempotency-Key": "test-key-xor-none"}
    payload = {"aspect_ratios": ["16:9"]}
    res = await client.post("/api/v1/broll/jobs", json=payload, headers=headers)
    assert res.status_code == 422
    body = res.json()
    assert body["error"]["code"] == "INVALID_INPUT_MODE"


@pytest.mark.asyncio
async def test_strict_xor_primary_input_mode_multiple(client: httpx.AsyncClient):
    """POST with both script and audio_url returns 422 INVALID_INPUT_MODE."""
    headers = {"Idempotency-Key": "test-key-xor-multi"}
    payload = {
        "script": "Some script",
        "audio_url": "https://example.com/audio.mp3",
    }
    res = await client.post("/api/v1/broll/jobs", json=payload, headers=headers)
    assert res.status_code == 422
    body = res.json()
    assert body["error"]["code"] == "INVALID_INPUT_MODE"


@pytest.mark.asyncio
async def test_empty_script_validation(client: httpx.AsyncClient):
    """Empty or whitespace-only script returns 422 EMPTY_SCRIPT."""
    headers = {"Idempotency-Key": "test-key-empty-script"}
    res1 = await client.post("/api/v1/broll/jobs", json={"script": ""}, headers=headers)
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] == "EMPTY_SCRIPT"

    headers2 = {"Idempotency-Key": "test-key-ws-script"}
    res2 = await client.post("/api/v1/broll/jobs", json={"script": "   \n\t  "}, headers=headers2)
    assert res2.status_code == 422
    assert res2.json()["error"]["code"] == "EMPTY_SCRIPT"


@pytest.mark.asyncio
async def test_script_too_long(client: httpx.AsyncClient):
    """Script exceeding 15,000 chars returns 422 SCRIPT_TOO_LONG."""
    headers = {"Idempotency-Key": "test-key-long-script"}
    long_script = "a" * 15001
    res = await client.post("/api/v1/broll/jobs", json={"script": long_script}, headers=headers)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "SCRIPT_TOO_LONG"


@pytest.mark.asyncio
async def test_unsupported_aspect_ratio(client: httpx.AsyncClient):
    """Invalid aspect ratio returns 422 UNSUPPORTED_ASPECT_RATIO."""
    headers = {"Idempotency-Key": "test-key-bad-ratio"}
    payload = {
        "script": "A valid script.",
        "aspect_ratios": ["4:3"],
    }
    res = await client.post("/api/v1/broll/jobs", json=payload, headers=headers)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "UNSUPPORTED_ASPECT_RATIO"


@pytest.mark.asyncio
async def test_scene_sequence_validation(client: httpx.AsyncClient):
    """Empty scenes list or empty scene text returns 422 INVALID_SCENE_SEQUENCE."""
    headers = {"Idempotency-Key": "test-key-empty-scenes"}
    res1 = await client.post("/api/v1/broll/jobs", json={"scenes": []}, headers=headers)
    assert res1.status_code == 422
    assert res1.json()["error"]["code"] == "INVALID_SCENE_SEQUENCE"

    headers2 = {"Idempotency-Key": "test-key-empty-scene-text"}
    res2 = await client.post(
        "/api/v1/broll/jobs", json={"scenes": [{"text": "   "}]}, headers=headers2
    )
    assert res2.status_code == 422
    assert res2.json()["error"]["code"] in ["EMPTY_SCRIPT", "INVALID_SCENE_SEQUENCE"]


@pytest.mark.asyncio
async def test_job_not_found(client: httpx.AsyncClient):
    """GET for nonexistent job returns 404 JOB_NOT_FOUND."""
    res = await client.get("/api/v1/jobs/job_nonexistent_12345")
    assert res.status_code == 404
    body = res.json()
    assert body["error"]["code"] == "JOB_NOT_FOUND"
    assert body["error"]["retryable"] is False
