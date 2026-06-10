"""Integration tests for /v1/limits/* endpoints using fakeredis + in-memory DB."""

from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_health_live(client):
    r = await client.get("/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_check_missing_auth(client):
    # Override auth header
    r = await client.post(
        "/v1/limits/check",
        json={
            "user_id": str(uuid.uuid4()),
            "estimated_input_tokens": 100,
            "estimated_output_tokens": 50,
            "model_id": "gpt-4o",
            "request_id": str(uuid.uuid4()),
        },
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_check_allowed(client):
    r = await client.post(
        "/v1/limits/check",
        json={
            "user_id": str(uuid.uuid4()),
            "estimated_input_tokens": 100,
            "estimated_output_tokens": 50,
            "model_id": "gpt-4o",
            "request_id": str(uuid.uuid4()),
        },
    )
    # New user → free tier (10k daily) — 150 tokens should pass
    assert r.status_code == 200
    body = r.json()
    assert body["allowed"] is True
    assert "request_id" in body
    assert "remaining_tokens" in body


@pytest.mark.asyncio
async def test_check_consume_round_trip(client):
    request_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())

    check_r = await client.post(
        "/v1/limits/check",
        json={
            "user_id": user_id,
            "estimated_input_tokens": 500,
            "estimated_output_tokens": 200,
            "model_id": "gpt-4o",
            "request_id": request_id,
        },
    )
    assert check_r.status_code == 200

    consume_r = await client.post(
        "/v1/limits/consume",
        json={
            "user_id": user_id,
            "request_id": request_id,
            "actual_input_tokens": 450,
            "actual_output_tokens": 180,
            "model_id": "gpt-4o",
        },
    )
    assert consume_r.status_code == 200
    body = consume_r.json()
    assert body["consumed"] is True
    assert body["total_deducted"] == 630  # (450+180)*1.0
    assert body["refunded"] == 70        # reserved 700, actual 630


@pytest.mark.asyncio
async def test_usage_endpoint(client):
    user_id = str(uuid.uuid4())
    r = await client.get(f"/v1/limits/usage?user_id={user_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["daily_used"] == 0
    assert body["tier"] == "free"


@pytest.mark.asyncio
async def test_history_endpoint(client):
    user_id = str(uuid.uuid4())
    r = await client.get(f"/v1/limits/history?user_id={user_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["records"] == []
