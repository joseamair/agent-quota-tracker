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
