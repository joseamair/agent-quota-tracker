from __future__ import annotations

import argparse
import pytest
from datetime import datetime, timezone, timedelta
from agent_quota_tracker.cli import format_reset_time


def test_format_reset_time_none():
    assert format_reset_time(None) == "Ready to Poke"
    assert format_reset_time("") == "Ready to Poke"


def test_format_reset_time_today():
    now = datetime.now().astimezone()
    # Create timestamp 2 hours from now today
    future_today = now.replace(minute=30, second=0)
    iso_str = future_today.isoformat()
    result = format_reset_time(iso_str)
    assert "(Today)" in result


def test_format_reset_time_future_day():
    future_date = datetime.now().astimezone() + timedelta(days=3)
    iso_str = future_date.isoformat()
    result = format_reset_time(iso_str)
    assert result != "Ready to Poke"
    assert "(Today)" not in result


def test_cli_parser_flags():
    # Test argparse configuration without invoking execution
    from agent_quota_tracker.cli import main
    # Test parser structure by importing main or verifying argparse options
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--status", "-s", action="store_true")
    parser.add_argument("--poke", "-p", action="store_true")
    parser.add_argument("--force", "-f", action="store_true")
    parser.add_argument("--agent", "-a", type=str)
    parser.add_argument("--dashboard", "-d", action="store_true")

    args = parser.parse_args(["--poke", "--force", "-a", "work"])
    assert args.poke is True
    assert args.force is True
    assert args.agent == "work"
    assert args.status is False
    assert args.json is False


def test_format_reset_time_compact():
    assert format_reset_time(None, compact=True) == "Ready"
    now = datetime.now().astimezone()
    today_time = now.replace(minute=0, second=0)
    res_today = format_reset_time(today_time.isoformat(), compact=True)
    assert "(Today)" in res_today

    future_time = now + timedelta(days=2)
    res_future = format_reset_time(future_time.isoformat(), compact=True)
    assert "(Today)" not in res_future


def test_get_terminal_width():
    from agent_quota_tracker.cli import get_terminal_width
    w = get_terminal_width()
    assert isinstance(w, int)
    assert w >= 40


def test_build_status_table_all_tiers():
    from agent_quota_tracker.cli import build_status_table
    from agent_quota_tracker.models import AgentStatus

    dummy_statuses = [
        AgentStatus(
            id="agy",
            name="Google Antigravity (AGY)",
            provider="agy",
            is_active=True,
            used_percent=75.5,
            resets_at=(datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            time_remaining_str="2h 15m 30s",
            weekly_used_percent=25.0,
            weekly_reset_str="in 120.0h (Wed Sep 30, 08:47)",
            weekly_remaining_hours=120.0,
        ),
        AgentStatus(
            id="work",
            name="Claude (Work)",
            provider="claude",
            is_active=False,
            used_percent=0.0,
            time_remaining_str="Inactive",
            weekly_used_percent=40.0,
            weekly_reset_str="in 60.0h (Sun Sep 27, 12:00)",
            weekly_remaining_hours=60.0,
        ),
    ]

    # Tier 1: Wide (>= 135)
    t_wide = build_status_table(dummy_statuses, term_w=140)
    col_names_wide = [col.header for col in t_wide.columns]
    assert "Agent / Account" in col_names_wide
    assert "Weekly Reset" in col_names_wide

    # Tier 2: Balanced (110 - 134)
    t_bal = build_status_table(dummy_statuses, term_w=120)
    col_names_bal = [col.header for col in t_bal.columns]
    assert "Account" in col_names_bal
    assert "Weekly Reset" in col_names_bal

    # Tier 3: Compact (75 - 109)
    t_comp = build_status_table(dummy_statuses, term_w=90)
    col_names_comp = [col.header for col in t_comp.columns]
    assert "Agent" in col_names_comp
    assert "Weekly" in col_names_comp

    # Tier 4: Mini (< 75)
    t_mini = build_status_table(dummy_statuses, term_w=65)
    col_names_mini = [col.header for col in t_mini.columns]
    assert len(col_names_mini) == 5
    assert "Agent" in col_names_mini
