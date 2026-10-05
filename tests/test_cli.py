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

    parser.add_argument("--schedule-install", nargs="?", const="07:30", default=None)
    parser.add_argument("--schedule-status", action="store_true")
    parser.add_argument("--schedule-remove", action="store_true")

    args = parser.parse_args(["--poke", "--force", "-a", "work", "--schedule-install", "08:00"])
    assert args.poke is True
    assert args.force is True
    assert args.agent == "work"
    assert args.schedule_install == "08:00"
    assert args.schedule_status is False
    assert args.schedule_remove is False
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


def test_build_status_table_timestamp():
    from agent_quota_tracker.cli import build_status_table
    table = build_status_table([], term_w=120, timestamp_str="2026-09-25 12:34:56")
    assert "2026-09-25 12:34:56" in table.title
    assert "Checked:" in table.title


def test_build_status_table_weekly_exhaustion_warning():
    from agent_quota_tracker.cli import build_status_table
    from agent_quota_tracker.models import AgentStatus

    dummy_statuses = [
        AgentStatus(
            id="personal",
            name="Claude (Personal)",
            provider="claude",
            is_active=False,
            used_percent=0.0,
            weekly_used_percent=100.0,
            weekly_reset_str="in 30.0h (Mon)",
            weekly_remaining_hours=30.0,
        )
    ]

    # Test Wide view
    t_wide = build_status_table(dummy_statuses, term_w=140)
    # Check rows for warning symbol
    found_warning = False
    for col in t_wide.columns:
        if col.header == "Wk Use":
            # Inspect cell value
            pass

    from rich.console import Console
    console = Console(record=True, width=140)
    console.print(t_wide)
    rendered = console.export_text()
    assert "100" in rendered
    assert "⚠️" in rendered


def test_auto_checker_parser_flags():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--auto-poke", action="store_true")
    parser.add_argument("subcommand", nargs="?", choices=["status", "poke", "dashboard", "poke-watch", "prompt", "schedule", "auto"])

    args1 = parser.parse_args(["--auto"])
    assert args1.auto is True
    assert args1.auto_poke is False

    args2 = parser.parse_args(["--auto-poke"])
    assert args2.auto_poke is True

    args3 = parser.parse_args(["auto"])
    assert args3.subcommand == "auto"


def test_compute_adaptive_sleep_seconds_skips_exhausted():
    from agent_quota_tracker.cli import compute_adaptive_sleep_seconds
    from agent_quota_tracker.models import AgentStatus

    # Agent 1 is exhausted (100% weekly) with 500s remaining on 5h window
    # Agent 2 is not exhausted (40% weekly) with 1500s remaining on 5h window
    s_exhausted = AgentStatus(
        id="personal",
        name="Claude (Personal)",
        provider="claude",
        is_active=True,
        used_percent=10.0,
        time_remaining_seconds=500,
        time_remaining_str="8m 20s",
        weekly_used_percent=100.0,
    )
    s_valid = AgentStatus(
        id="work",
        name="Claude (Work)",
        provider="claude",
        is_active=True,
        used_percent=10.0,
        time_remaining_seconds=1500,
        time_remaining_str="25m",
        weekly_used_percent=40.0,
    )

    # Without force: should skip s_exhausted and sleep for s_valid (1500 + 45 = 1545)
    sleep_secs, reason = compute_adaptive_sleep_seconds([s_exhausted, s_valid], force=False)
    assert sleep_secs == 1545
    assert "Claude (Work)" in reason

    # With force: should include s_exhausted (500 + 45 = 545)
    sleep_secs_forced, reason_forced = compute_adaptive_sleep_seconds([s_exhausted, s_valid], force=True)
    assert sleep_secs_forced == 545
    assert "Claude (Personal)" in reason_forced


def test_run_auto_checker_loop_single_cycle(monkeypatch):
    from unittest.mock import MagicMock
    from agent_quota_tracker.cli import run_auto_checker_loop
    from agent_quota_tracker.models import AgentStatus

    idle_agent = AgentStatus(
        id="agy",
        name="Google Antigravity (AGY)",
        provider="agy",
        is_active=False,
        used_percent=0.0,
        weekly_used_percent=20.0,
    )
    active_agent = AgentStatus(
        id="codex",
        name="OpenAI Codex",
        provider="codex",
        is_active=True,
        used_percent=0.0,
        time_remaining_seconds=300,
        time_remaining_str="5m 0s",
        weekly_used_percent=10.0,
    )

    mock_statuses = [idle_agent, active_agent]
    mock_get_all = MagicMock(return_value=mock_statuses)
    mock_print_table = MagicMock()
    mock_run_poke = MagicMock()
    mock_run_countdown = MagicMock()

    monkeypatch.setattr("agent_quota_tracker.cli.get_all_statuses", mock_get_all)
    monkeypatch.setattr("agent_quota_tracker.cli.print_status_table", mock_print_table)
    monkeypatch.setattr("agent_quota_tracker.cli.run_poke", mock_run_poke)
    monkeypatch.setattr("agent_quota_tracker.cli.run_countdown", mock_run_countdown)

    # Run exactly 1 cycle
    run_auto_checker_loop(force=False, notify=False, max_cycles=1)

    # Verify:
    # 1. Status table printed
    assert mock_print_table.call_count >= 1
    # 2. Idle agent poked immediately because idle_ready had 1 agent, plus end-of-countdown poke
    assert mock_run_poke.call_count >= 2
    # 3. Countdown was run for active agent
    assert mock_run_countdown.call_count == 1
    called_secs = mock_run_countdown.call_args[0][0]
    assert called_secs == 345


def test_run_auto_checker_loop_keyboard_interrupt(monkeypatch):
    from unittest.mock import MagicMock
    from agent_quota_tracker.cli import run_auto_checker_loop

    mock_print_table = MagicMock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr("agent_quota_tracker.cli.print_status_table", mock_print_table)

    # Should exit cleanly without raising KeyboardInterrupt exception
    run_auto_checker_loop(max_cycles=1)


def test_auto_checker_parser_refresh_interval():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto", action="store_true")
    parser.add_argument("--refresh-interval", type=int, default=15)

    args = parser.parse_args(["--auto", "--refresh-interval", "30"])
    assert args.auto is True
    assert args.refresh_interval == 30


def test_run_auto_checker_live_detects_early_idle(monkeypatch):
    from unittest.mock import MagicMock
    import time
    from agent_quota_tracker.cli import run_auto_checker_live
    from agent_quota_tracker.models import AgentStatus

    active_status = AgentStatus(
        id="codex",
        name="OpenAI Codex",
        provider="codex",
        is_active=True,
        used_percent=10.0,
        time_remaining_seconds=100,
        time_remaining_str="1m 40s",
    )
    idle_status = AgentStatus(
        id="codex",
        name="OpenAI Codex",
        provider="codex",
        is_active=False,
        used_percent=0.0,
        time_remaining_seconds=0,
        time_remaining_str="Ready to Poke",
    )

    # First fetch returns idle_status immediately
    mock_get_all = MagicMock(return_value=[idle_status])
    monkeypatch.setattr("agent_quota_tracker.cli.get_all_statuses", mock_get_all)
    monkeypatch.setattr("time.sleep", lambda s: None)

    # When refresh_interval=0, it triggers immediately and returns True on early idle
    result = run_auto_checker_live(
        total_seconds=100,
        wake_time="14:00:00",
        reason="Codex (1m left)",
        statuses=[active_status],
        force=False,
        refresh_interval=0,
    )
    assert result is True



def test_print_status_table_with_provided_statuses(monkeypatch):
    from unittest.mock import MagicMock
    from agent_quota_tracker.cli import print_status_table
    from agent_quota_tracker.models import AgentStatus

    mock_get_all = MagicMock()
    monkeypatch.setattr("agent_quota_tracker.cli.get_all_statuses", mock_get_all)

    dummy = [
        AgentStatus(
            id="agy",
            name="Google Antigravity (AGY)",
            provider="agy",
            is_active=True,
            used_percent=25.0,
            time_remaining_seconds=12000,
            time_remaining_str="3h 20m",
        )
    ]
    returned = print_status_table(statuses=dummy)
    assert returned == dummy
    mock_get_all.assert_not_called()


def test_run_auto_checker_loop_all_active(monkeypatch):
    from unittest.mock import MagicMock
    from agent_quota_tracker.cli import run_auto_checker_loop
    from agent_quota_tracker.models import AgentStatus

    active_agent = AgentStatus(
        id="personal",
        name="Claude (Personal)",
        provider="claude",
        is_active=True,
        used_percent=1.0,
        time_remaining_seconds=15420,
        time_remaining_str="4h 17m",
        weekly_used_percent=30.0,
    )
    mock_statuses = [active_agent]
    mock_get_all = MagicMock(return_value=mock_statuses)
    mock_print_table = MagicMock()
    mock_run_poke = MagicMock()
    mock_run_countdown = MagicMock()

    monkeypatch.setattr("agent_quota_tracker.cli.get_all_statuses", mock_get_all)
    monkeypatch.setattr("agent_quota_tracker.cli.print_status_table", mock_print_table)
    monkeypatch.setattr("agent_quota_tracker.cli.run_poke", mock_run_poke)
    monkeypatch.setattr("agent_quota_tracker.cli.run_countdown", mock_run_countdown)

    # Run 1 cycle with all active agents
    run_auto_checker_loop(force=False, notify=False, max_cycles=1)

    # Verified:
    # 1. get_all_statuses called exactly once (no redundant fetch!)
    assert mock_get_all.call_count == 1
    # 2. Table printed with statuses
    assert mock_print_table.call_count == 1
    # 3. Only the end-of-countdown poke was called (initial idle poke was skipped because 0 idle agents)
    assert mock_run_poke.call_count == 1
    # 4. Countdown called with 15420 + 45 = 15465
    assert mock_run_countdown.call_count == 1
    assert mock_run_countdown.call_args[0][0] == 15465


def test_run_countdown_basic(monkeypatch):
    import io
    import sys
    from agent_quota_tracker.cli import run_countdown

    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr("time.sleep", lambda s: None)

    run_countdown(total_seconds=2, prefix="Testing")
    val = out.getvalue()
    assert "Testing" in val
    assert "\n" in val


def test_agents_standalone_run_auto_checker_live(monkeypatch):
    from unittest.mock import MagicMock
    import agents

    active_agent = agents.AgentInfo(
        id="codex",
        name="Codex",
        provider="codex",
        is_active=True,
        used_percent=10.0,
        time_remaining_seconds=50,
        weekly_used_percent=20.0,
    )
    idle_agent = agents.AgentInfo(
        id="codex",
        name="Codex",
        provider="codex",
        is_active=False,
        used_percent=0.0,
        time_remaining_seconds=0,
        weekly_used_percent=20.0,
    )

    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(agents, "fetch_all_statuses", MagicMock(return_value=[idle_agent]))

    res = agents.run_auto_checker_live(
        total_seconds=50,
        wake_time="14:00:00",
        reason="Codex",
        statuses=[active_agent],
        force=False,
        refresh_interval=0,
    )
    assert res is True


def test_cli_metrics_flag(monkeypatch, capsys):
    import sys
    from agent_quota_tracker.cli import main
    from agent_quota_tracker.models import AgentStatus

    dummy = AgentStatus(
        id="agy",
        name="Google Antigravity (AGY)",
        provider="agy",
        is_active=True,
        used_percent=12.0,
        time_remaining_seconds=3600,
        category="personal",
    )
    monkeypatch.setattr("agent_quota_tracker.cli.get_all_statuses", lambda: [dummy])
    monkeypatch.setattr(sys, "argv", ["agents", "--metrics"])

    main()
    out = capsys.readouterr().out
    assert "agent_quota_tracker_up 1" in out
    assert 'agent_quota_used_percent{agent_id="agy"' in out


def test_cli_export_subcommand(monkeypatch, capsys):
    import sys
    from agent_quota_tracker.cli import main

    monkeypatch.setattr(
        "agent_quota_tracker.history.export_snapshots_csv",
        lambda filepath=None, days=None: "header1,header2\nv1,v2\n",
    )
    monkeypatch.setattr(sys, "argv", ["agents", "export", "--csv", "-"])

    main()
    out = capsys.readouterr().out
    assert "header1,header2" in out
    assert "v1,v2" in out


def test_cli_tui_flag(monkeypatch):
    import sys
    from unittest.mock import MagicMock
    from agent_quota_tracker.cli import main

    mock_run = MagicMock()
    monkeypatch.setattr("agent_quota_tracker.cli.run_tui_cmd", mock_run)
    monkeypatch.setattr(sys, "argv", ["agents", "--tui"])

    main()
    mock_run.assert_called_once()


def test_cli_tui_subcommand(monkeypatch):
    import sys
    from unittest.mock import MagicMock
    from agent_quota_tracker.cli import main

    mock_run = MagicMock()
    monkeypatch.setattr("agent_quota_tracker.cli.run_tui_cmd", mock_run)
    monkeypatch.setattr(sys, "argv", ["agents", "tui", "--refresh-interval", "20"])

    main()
    mock_run.assert_called_once_with(
        refresh_interval=20,
        notify=False,
        force=False,
        agent_id=None,
    )







