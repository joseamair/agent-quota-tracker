from __future__ import annotations

import pytest
from agent_quota_tracker.models import AgentStatus, PokeResult


def test_agent_status_active():
    status = AgentStatus(
        id="agy",
        name="Google Antigravity (AGY)",
        provider="agy",
        is_active=True,
        used_percent=15.367,
        resets_at="2026-09-25T04:30:00Z",
        resets_at_timestamp=1790310600.0,
        time_remaining_seconds=14400,
        time_remaining_str="4h 00m 00s",
        weekly_used_percent=22.84,
        weekly_reset_str="in 120.5h (Wed Sep 30, 08:00)",
        category="personal",
    )

    data = status.to_dict()
    assert data["id"] == "agy"
    assert data["name"] == "Google Antigravity (AGY)"
    assert data["provider"] == "agy"
    assert data["category"] == "personal"
    assert data["is_active"] is True
    assert data["used_percent"] == 15.4  # Rounded to 1 decimal place
    assert data["weekly_used_percent"] == 22.8
    assert data["time_remaining_seconds"] == 14400
    assert data["time_remaining_str"] == "4h 00m 00s"
    assert data["error"] is None


def test_agent_status_inactive():
    status = AgentStatus(
        id="work",
        name="Claude (Work)",
        provider="claude",
        is_active=False,
        used_percent=0.0,
        category="work",
    )

    data = status.to_dict()
    assert data["id"] == "work"
    assert data["category"] == "work"
    assert data["is_active"] is False
    assert data["used_percent"] == 0.0
    assert data["weekly_used_percent"] is None
    assert data["time_remaining_seconds"] == 0
    assert data["time_remaining_str"] == "Inactive"


def test_poke_result_serialization():
    result = PokeResult(
        agent_id="codex",
        agent_name="OpenAI Codex",
        action_taken="poked",
        message="Verified ACTIVE (4h 59m remaining, 1.0% used)",
        reply="Hello! How can I assist you today?",
        verified_active=True,
        time_remaining_str="4h 59m",
        used_percent=1.0,
    )

    data = result.to_dict()
    assert data["agent_id"] == "codex"
    assert data["action_taken"] == "poked"
    assert data["verified_active"] is True
    assert data["reply"] == "Hello! How can I assist you today?"
    assert data["used_percent"] == 1.0
