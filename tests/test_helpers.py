from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from agent_quota_tracker.trackers.base import (
    format_duration,
    calculate_weekly_reset,
    extract_reply_snippet,
)


def test_format_duration():
    assert format_duration(0) == "0s"
    assert format_duration(-5) == "0s"
    assert format_duration(45) == "45s"
    assert format_duration(120) == "2m"
    assert format_duration(125) == "2m 5s"
    assert format_duration(3600) == "1h"
    assert format_duration(3665) == "1h 1m 5s"
    assert format_duration(18000) == "5h"


def test_calculate_weekly_reset_none():
    hours, text = calculate_weekly_reset(None)
    assert hours is None
    assert text == "-"

    hours, text = calculate_weekly_reset("")
    assert hours is None
    assert text == "-"


def test_calculate_weekly_reset_future():
    future_time = datetime.now(timezone.utc) + timedelta(hours=48, minutes=30)
    iso_str = future_time.isoformat()
    hours, text = calculate_weekly_reset(iso_str)
    assert hours is not None
    assert 48.0 <= hours <= 49.0
    assert text.startswith("in ")
    assert "h (" in text


def test_calculate_weekly_reset_past():
    past_time = datetime.now(timezone.utc) - timedelta(hours=2)
    iso_str = past_time.isoformat()
    hours, text = calculate_weekly_reset(iso_str)
    assert hours == 0.0
    assert text == "Reset due"


def test_extract_reply_snippet_clean():
    output = "Hello! I am ready to help you with your coding tasks."
    snippet = extract_reply_snippet(output)
    assert snippet == "Hello! I am ready to help you with your coding tasks."


def test_extract_reply_snippet_filters_headers():
    raw_output = """
OpenAI Codex v0.42.0
Workdir: /workspace/project
Model: gpt-4o
Tokens used: 128
--------
I am doing great! How can I assist you today with agent-quota-tracker?
"""
    snippet = extract_reply_snippet(raw_output)
    assert snippet == "I am doing great! How can I assist you today with agent-quota-tracker?"


def test_extract_reply_snippet_empty():
    assert extract_reply_snippet("") == "(no reply text captured)"
    assert extract_reply_snippet("   ") == "(no reply text captured)"


def test_extract_reply_snippet_truncation():
    long_text = "A" * 200
    snippet = extract_reply_snippet(long_text, max_chars=50)
    assert len(snippet) == 50
    assert snippet.endswith("...")


def test_parse_duration():
    from agent_quota_tracker.trackers.base import parse_duration
    assert parse_duration(None) is None
    assert parse_duration("") is None
    assert parse_duration("auto") is None
    assert parse_duration(120) == 120
    assert parse_duration("30m") == 1800
    assert parse_duration("2h") == 7200
    assert parse_duration("1h 30m") == 5400
    assert parse_duration("45s") == 45
    assert parse_duration("7200") == 7200
    assert parse_duration("invalid_string") is None


def test_parse_target_time():
    from agent_quota_tracker.trackers.base import parse_target_time
    # Mock current time as 09:00:00 today
    mock_now = datetime(2026, 9, 25, 9, 0, 0)
    
    # Target in the future today (14:30)
    target_dt, delta = parse_target_time("14:30", now_dt=mock_now)
    assert target_dt == datetime(2026, 9, 25, 14, 30, 0)
    assert delta == (5 * 3600) + (30 * 60)

    # Target in the past today (07:30) -> should schedule for tomorrow
    target_dt_tmr, delta_tmr = parse_target_time("07:30", now_dt=mock_now)
    assert target_dt_tmr == datetime(2026, 9, 26, 7, 30, 0)
    assert delta_tmr == (22 * 3600) + (30 * 60)

    # Invalid time format raises ValueError
    with pytest.raises(ValueError):
        parse_target_time("invalid")
    with pytest.raises(ValueError):
        parse_target_time("25:00")


def test_compute_adaptive_sleep_seconds():
    from agent_quota_tracker.cli import compute_adaptive_sleep_seconds
    from agent_quota_tracker.models import AgentStatus

    # No active agents
    s1 = AgentStatus(id="a1", name="A1", provider="p", is_active=False, used_percent=0.0)
    s2 = AgentStatus(id="a2", name="A2", provider="p", is_active=False, used_percent=0.0)
    sleep_secs, reason = compute_adaptive_sleep_seconds([s1, s2])
    assert sleep_secs == 120
    assert "idle" in reason.lower()

    # Active agent with 1000s remaining
    s3 = AgentStatus(id="a3", name="Claude Work", provider="p", is_active=True, used_percent=10.0, time_remaining_seconds=1000)
    s4 = AgentStatus(id="a4", name="AGY", provider="p", is_active=True, used_percent=50.0, time_remaining_seconds=3000)
    sleep_secs, reason = compute_adaptive_sleep_seconds([s1, s3, s4])
    assert sleep_secs == 1000 + 45
    assert "Claude Work" in reason

