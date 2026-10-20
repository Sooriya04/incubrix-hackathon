"""Tests for SQLite-backed Job History and Script Generation Engine."""

import pytest
import httpx
from incubrix.models import JobRecord
from incubrix.script_generator import (
    clean_voiceover_sentence,
    extract_topic_and_duration_from_prompt,
    format_duration,
    generate_script_from_topic,
    parse_duration_seconds,
)
from incubrix.storage import job_store


def test_duration_parsing_and_formatting():
    assert parse_duration_seconds("30s") == 30
    assert parse_duration_seconds("30 sec") == 30
    assert parse_duration_seconds("1:00 min") == 60
    assert parse_duration_seconds("1:30 min") == 90
    assert parse_duration_seconds("3:00 min") == 180
    assert parse_duration_seconds("3 minutes") == 180
    assert parse_duration_seconds("5 min") == 300

    assert format_duration(30) == "30 sec"
    assert format_duration(90) == "1:30 min"
    assert format_duration(180) == "3:00 min"


def test_clean_voiceover_sentence():
    raw1 = "Scene 1: Artificial intelligence is transforming engineering."
    assert clean_voiceover_sentence(raw1) == "Artificial intelligence is transforming engineering."

    raw2 = "[Scene 02] - Autonomous agents execute multi-step workflows."
    assert clean_voiceover_sentence(raw2) == "Autonomous agents execute multi-step workflows."

    raw3 = "1. Perception allows real-time environmental monitoring."
    assert clean_voiceover_sentence(raw3) == "Perception allows real-time environmental monitoring."


def test_extract_topic_and_duration_from_prompt():
    prompt = "Explain AI agents (3 minutes)"
    topic, dur = extract_topic_and_duration_from_prompt(prompt)
    assert "AI agents" in topic
    assert dur == 180

    prompt2 = "Phone battery preservation techniques"
    topic2, dur2 = extract_topic_and_duration_from_prompt(prompt2)
    assert topic2 == "Phone battery preservation techniques"
    assert dur2 == 90


@pytest.mark.asyncio
async def test_script_generation_deterministic():
    res = await generate_script_from_topic("Kubernetes Cluster Architecture", duration_sec=90)
    assert res["duration_sec"] == 90
    assert res["scene_count"] >= 3
    assert res["actual_words"] >= 35
    for s in res["scenes"]:
        assert not s["text"].lower().startswith("scene ")


@pytest.mark.asyncio
async def test_sqlite_job_history_and_rename(client: httpx.AsyncClient):
    # 1. Fetch history from SQLite
    res = await client.get("/api/v1/jobs")
    assert res.status_code == 200
    jobs = res.json()
    assert isinstance(jobs, list)

    # 2. Test renaming a job
    if jobs:
        target_id = jobs[0]["job_id"]
        patch_res = await client.patch(
            f"/api/v1/jobs/{target_id}/title",
            json={"title": "Custom Test Video Title"},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["friendly_title"] == "Custom Test Video Title"


@pytest.mark.asyncio
async def test_api_script_generate_endpoint(client: httpx.AsyncClient):
    res = await client.post(
        "/api/v1/script/generate",
        json={"topic": "Microservices vs Monoliths", "duration": "1:00 min"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["duration_sec"] == 60
    assert data["scene_count"] >= 2
    assert "script" in data
