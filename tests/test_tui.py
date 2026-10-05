import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from agent_quota_tracker.models import AgentStatus, PokeResult
from agent_quota_tracker.tui import (
    AgentTUI,
    format_reset_time_compact,
    render_progress_bar,
    run_tui,
)


def sample_statuses():
    now_utc = datetime.now(timezone.utc)
    resets_in_3h = (now_utc + timedelta(hours=3, minutes=15)).isoformat()
    weekly_resets = (now_utc + timedelta(days=4)).isoformat()

    return [
        AgentStatus(
            id="claude-personal",
            name="Claude (Personal)",
            provider="claude",
            category="personal",
            is_active=True,
            used_percent=42.5,
            resets_at=resets_in_3h,
            time_remaining_seconds=11700,
            time_remaining_str="3h 15m",
            weekly_used_percent=65.0,
            weekly_resets_at=weekly_resets,
            weekly_remaining_hours=96.0,
            weekly_reset_str="in 96.0h (Fri Oct 09, 12:00)",
            auth_status="valid",
        ),
        AgentStatus(
            id="agy",
            name="Google Antigravity (AGY)",
            provider="agy",
            category="personal",
            is_active=False,
            used_percent=0.0,
            resets_at=None,
            time_remaining_seconds=0,
            time_remaining_str="Inactive",
            weekly_used_percent=12.0,
            weekly_reset_str="in 120.0h (Sat Oct 10, 08:00)",
            auth_status="valid",
        ),
        AgentStatus(
            id="codex",
            name="OpenAI Codex",
            provider="codex",
            category="personal",
            is_active=False,
            used_percent=88.0,
            resets_at=None,
            time_remaining_seconds=0,
            time_remaining_str="Inactive",
            auth_status="expired",
            remediation_hint="codex login",
        ),
    ]


def test_render_progress_bar():
    # 0%
    bar0 = render_progress_bar(0.0, width=10)
    assert "░░░░░░░░░░" in bar0

    # 50%
    bar50 = render_progress_bar(50.0, width=10)
    assert "█████" in bar50
    assert "░░░░░" in bar50

    # 100%
    bar100 = render_progress_bar(100.0, width=10)
    assert "██████████" in bar100
    assert "\033[1;31m" in bar100  # Bold red for high usage


def test_format_reset_time_compact():
    assert format_reset_time_compact(None) == "Ready to Poke"
    assert format_reset_time_compact("") == "Ready to Poke"

    now_iso = datetime.now(timezone.utc).isoformat()
    formatted = format_reset_time_compact(now_iso)
    assert "Today" in formatted or ":" in formatted


def test_agent_tui_navigation():
    tui = AgentTUI(refresh_interval=15)
    tui.statuses = sample_statuses()
    assert tui.selected_index == 0
    assert tui.get_selected_agent().name == "Claude (Personal)"

    # Move down
    tui.handle_key("down")
    assert tui.selected_index == 1
    assert tui.get_selected_agent().name == "Google Antigravity (AGY)"

    # Move down again
    tui.handle_key("j")
    assert tui.selected_index == 2
    assert tui.get_selected_agent().name == "OpenAI Codex"

    # Wrap around
    tui.handle_key("down")
    assert tui.selected_index == 0

    # Move up (wrap back to end)
    tui.handle_key("up")
    assert tui.selected_index == 2

    tui.handle_key("k")
    assert tui.selected_index == 1


def test_agent_tui_render():
    tui = AgentTUI(refresh_interval=15)
    tui.statuses = sample_statuses()
    output = tui.render_to_string(term_width=110, term_height=30)

    # Check header
    assert "⚡ AGENT QUOTA TRACKER TUI" in output
    assert "Active: 1/3" in output

    # Check table content
    assert "Claude (Personal)" in output
    assert "Google Antigravity (AGY)" in output
    assert "OpenAI Codex" in output
    assert "● ACTIVE" in output
    assert "○ INACTIVE" in output
    assert "⚠️ EXPIRED" in output

    # Check inspector
    assert "Account Inspector" in output
    assert "5h Status:" in output

    # Check hotkey bar
    assert "[p]" in output and "Poke" in output
    assert "[q]" in output and "Quit" in output


def test_agent_tui_help_modal():
    tui = AgentTUI(refresh_interval=15)
    tui.statuses = sample_statuses()

    assert not tui.show_help
    tui.handle_key("?")
    assert tui.show_help

    help_output = tui.render_to_string(term_width=100, term_height=30)
    assert "KEYBOARD REFERENCE" in help_output
    assert "5-Hour Rolling Threshold Mechanics:" in help_output

    # Closing help modal
    tui.handle_key("esc")
    assert not tui.show_help


@patch("agent_quota_tracker.tui.poke_all")
def test_agent_tui_poke_selected(mock_poke):
    mock_poke.return_value = [
        PokeResult(
            agent_id="agy",
            agent_name="Google Antigravity (AGY)",
            action_taken="poked",
            message="Window started with 100% quota.",
        )
    ]

    tui = AgentTUI()
    tui.statuses = sample_statuses()
    tui.selected_index = 1  # AGY

    with patch.object(tui, "fetch_statuses"):
        tui.poke_selected(force=False)

    mock_poke.assert_called_once_with(force=False, agent_id="agy")
    assert "Primed Google Antigravity (AGY)" in tui.status_msg
    assert tui.status_type == "success"


@patch("agent_quota_tracker.tui.poke_all")
def test_agent_tui_poke_all_idle(mock_poke):
    mock_poke.return_value = [
        PokeResult(
            agent_id="agy",
            agent_name="Google Antigravity (AGY)",
            action_taken="poked",
            message="Window started.",
        ),
        PokeResult(
            agent_id="claude-personal",
            agent_name="Claude (Personal)",
            action_taken="skipped",
            message="Already active.",
        ),
    ]

    tui = AgentTUI()
    tui.statuses = sample_statuses()

    with patch.object(tui, "fetch_statuses"):
        tui.poke_all_idle()

    mock_poke.assert_called_once_with(force=False, agent_id=None)
    assert "Primed 1 agent(s): Google Antigravity (AGY)" in tui.status_msg
    assert tui.status_type == "success"


def test_agent_tui_tick_second():
    tui = AgentTUI()
    tui.statuses = sample_statuses()
    initial_secs = tui.statuses[0].time_remaining_seconds

    tui.tick_second()
    assert tui.statuses[0].time_remaining_seconds == initial_secs - 1


@patch("agent_quota_tracker.tui.enter_alt_screen")
@patch("agent_quota_tracker.tui.leave_alt_screen")
@patch("agent_quota_tracker.tui.get_all_statuses")
@patch("agent_quota_tracker.tui.read_key")
def test_agent_tui_run_loop(mock_read_key, mock_get_statuses, mock_leave, mock_enter):
    mock_get_statuses.return_value = sample_statuses()
    mock_read_key.side_effect = ["down", "q"]

    tui = AgentTUI()
    tui.run()

    mock_enter.assert_called_once()
    mock_leave.assert_called_once()
    assert not tui.running
    assert tui.selected_index == 1


# ==============================================================================
# Quick Filter Mode Tests
# ==============================================================================

def test_agent_tui_quick_filter_typing_and_navigation():
    tui = AgentTUI()
    tui.statuses = sample_statuses()

    # Enter filter mode with '/'
    tui.handle_key("/")
    assert tui.filter_mode is True
    assert tui.filter_query == ""

    # Type 'a', 'g', 'y'
    tui.handle_key("a")
    tui.handle_key("g")
    tui.handle_key("y")
    assert tui.filter_query == "agy"

    filtered = tui.get_filtered_statuses()
    assert len(filtered) == 1
    assert filtered[0].id == "agy"

    # Backspace
    tui.handle_key("backspace")
    assert tui.filter_query == "ag"
    assert len(tui.get_filtered_statuses()) == 1

    # Confirm with Enter
    tui.handle_key("enter")
    assert tui.filter_mode is False
    assert tui.filter_query == "ag"

    # Render with filter active
    out = tui.render_to_string(term_width=100, term_height=30)
    assert "Filter: 'ag'" in out
    assert "Google Antigravity (AGY)" in out
    assert "Claude (Personal)" not in out

    # Clear filter with Esc
    tui.handle_key("esc")
    assert tui.filter_query == ""
    assert len(tui.get_filtered_statuses()) == 3


def test_agent_tui_quick_filter_semantic_keywords():
    tui = AgentTUI()
    tui.statuses = sample_statuses()

    # Filter 'idle'
    tui.filter_query = "idle"
    idle_accounts = tui.get_filtered_statuses()
    # AGY and Codex are inactive
    assert len(idle_accounts) == 2
    assert all(not s.is_active for s in idle_accounts)

    # Filter 'active'
    tui.filter_query = "active"
    active_accounts = tui.get_filtered_statuses()
    assert len(active_accounts) == 1
    assert active_accounts[0].id == "claude-personal"

    # Filter 'expired'
    tui.filter_query = "expired"
    expired_accounts = tui.get_filtered_statuses()
    assert len(expired_accounts) == 1
    assert expired_accounts[0].id == "codex"


@patch("agent_quota_tracker.tui.poke_all")
def test_agent_tui_quick_filter_poke_filtered_idle(mock_poke):
    mock_poke.return_value = [
        PokeResult(agent_id="agy", agent_name="Google Antigravity (AGY)", action_taken="poked", message="Primed")
    ]
    tui = AgentTUI()
    tui.statuses = sample_statuses()

    # Filter to only 'agy'
    tui.filter_query = "agy"

    with patch.object(tui, "fetch_statuses"):
        tui.poke_all_idle()

    # Should only poke AGY, not all idle
    mock_poke.assert_called_once_with(force=False, agent_id="agy")
    assert "Primed 1 agent(s): Google Antigravity (AGY)" in tui.status_msg

