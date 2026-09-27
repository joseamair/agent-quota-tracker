from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

from agent_quota_tracker.cache import get_cache_file, load_cache, save_cache
from agent_quota_tracker.models import AgentStatus
from agent_quota_tracker.prompt import (
    compute_live_prompt_data,
    format_duration_short,
    format_prompt,
)


def test_format_duration_short():
    assert format_duration_short(0) == "0m"
    assert format_duration_short(-10) == "0m"
    assert format_duration_short(45) == "1m"
    assert format_duration_short(1800) == "30m"
    assert format_duration_short(3600) == "1h"
    assert format_duration_short(7260) == "2h01m"
    assert format_duration_short(8040) == "2h14m"


def test_compute_live_prompt_data_active():
    now_ts = 10000.0
    cache = {
        "updated_at": "2026-09-27T10:00:00+00:00",
        "accounts": [
            {
                "id": "agy",
                "name": "Google Antigravity",
                "is_active": True,
                "resets_at_timestamp": now_ts + 3600,  # 1h left
            },
            {
                "id": "codex",
                "name": "OpenAI Codex",
                "is_active": True,
                "resets_at_timestamp": now_ts + 7200,  # 2h left
            },
            {
                "id": "claude-work",
                "name": "Claude Work",
                "is_active": False,
                "resets_at_timestamp": None,
            },
        ],
    }

    data = compute_live_prompt_data(cache, now_ts=now_ts)
    assert data["active"] == 2
    assert data["total"] == 3
    assert data["min_remaining"] == "1h"
    assert data["min_remaining_seconds"] == 3600
    assert data["max_remaining"] == "2h"
    assert data["status"] == "Active"
    assert data["icon"] == "⚡"
    assert data["percent"] == "67%"


def test_compute_live_prompt_data_dynamic_expiry():
    # Account had 10 minutes left at 10000, but current time is 11000 (expired 400s ago)
    cache = {
        "accounts": [
            {
                "id": "agy",
                "is_active": True,
                "resets_at_timestamp": 10600.0,
            },
        ]
    }

    # Before expiry
    data_before = compute_live_prompt_data(cache, now_ts=10000.0)
    assert data_before["active"] == 1
    assert data_before["min_remaining"] == "10m"

    # After expiry (dynamic cooldown without needing API query)
    data_after = compute_live_prompt_data(cache, now_ts=11000.0)
    assert data_after["active"] == 0
    assert data_after["min_remaining"] == "Idle"
    assert data_after["icon"] == "○"
    assert data_after["status"] == "Idle"


def test_compute_live_prompt_data_all_idle():
    cache = {
        "accounts": [
            {"id": "agy", "is_active": False},
            {"id": "codex", "is_active": False},
        ]
    }
    data = compute_live_prompt_data(cache)
    assert data["active"] == 0
    assert data["total"] == 2
    assert data["min_remaining"] == "Idle"
    assert data["icon"] == "○"
    assert data["status"] == "Idle"
    assert data["percent"] == "0%"


def test_format_prompt_presets():
    now_ts = 10000.0
    cache = {
        "accounts": [
            {
                "id": "agy",
                "is_active": True,
                "resets_at_timestamp": now_ts + 5400,  # 1h30m
            },
            {
                "id": "codex",
                "is_active": True,
                "resets_at_timestamp": now_ts + 7200,  # 2h
            },
            {
                "id": "claude-work",
                "is_active": False,
            },
        ]
    }

    with patch("time.time", return_value=now_ts):
        default_fmt = format_prompt("default", cache=cache)
        assert default_fmt == "[⚡ 2/3 Active • 1h30m]"

        compact_fmt = format_prompt("compact", cache=cache)
        assert compact_fmt == "⚡2/3 1h30m"

        minimal_fmt = format_prompt("minimal", cache=cache)
        assert minimal_fmt == "🤖 2/3"

        tmux_fmt = format_prompt("tmux", cache=cache)
        assert "2/3 (1h30m)" in tmux_fmt

        json_fmt = format_prompt("json", cache=cache)
        parsed = json.loads(json_fmt)
        assert parsed["active"] == 2
        assert parsed["min_remaining"] == "1h30m"


def test_format_prompt_custom_template():
    now_ts = 10000.0
    cache = {
        "accounts": [
            {"id": "agy", "is_active": True, "resets_at_timestamp": now_ts + 3600},
            {"id": "codex", "is_active": False},
        ]
    }
    with patch("time.time", return_value=now_ts):
        res = format_prompt("Quota: {active} of {total} ({percent}) - {status} [{min_remaining}]", cache=cache)
        assert res == "Quota: 1 of 2 (50%) - Active [1h]"


def test_save_and_load_cache(tmp_path, monkeypatch):
    cache_file = tmp_path / "cache.json"
    monkeypatch.setattr("agent_quota_tracker.cache.get_cache_file", lambda: cache_file)

    statuses = [
        AgentStatus(
            id="agy",
            name="Google Antigravity",
            provider="agy",
            is_active=True,
            used_percent=25.0,
            time_remaining_seconds=3600,
            resets_at_timestamp=time.time() + 3600,
        ),
        AgentStatus(
            id="codex",
            name="OpenAI Codex",
            provider="codex",
            is_active=False,
            used_percent=0.0,
        ),
    ]

    save_cache(statuses)
    assert cache_file.exists()

    loaded = load_cache()
    assert loaded is not None
    assert loaded["active_count"] == 1
    assert loaded["total_count"] == 2
    assert len(loaded["accounts"]) == 2
    assert loaded["accounts"][0]["name"] == "Google Antigravity"
