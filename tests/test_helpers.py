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
