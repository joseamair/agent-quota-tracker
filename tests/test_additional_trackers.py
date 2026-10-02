from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_quota_tracker.trackers.cursor import CursorTracker
from agent_quota_tracker.trackers.windsurf import WindsurfTracker
from agent_quota_tracker.trackers.copilot import CopilotTracker
from agent_quota_tracker.trackers.aider import AiderTracker


# ==============================================================================
# Cursor Tracker Tests
# ==============================================================================

def test_cursor_status_with_mock_api():
    tracker = CursorTracker(access_token="test-token-123")
    mock_data = {
        "gpt-4": {
            "numRequests": 125,
            "maxRequestUsage": 500,
        },
        "startOfMonth": "2026-10-01T00:00:00.000Z",
    }

    with patch.object(tracker, "_query_usage_api", return_value=(mock_data, None)):
        status = tracker.get_status()
        assert status.provider == "cursor"
        assert status.is_active is True
        assert status.used_percent == 25.0
        assert status.weekly_used_percent == 25.0
        assert status.status_label == "Active"
        assert status.details["num_requests"] == 125
        assert status.details["max_requests"] == 500


def test_cursor_status_unconfigured():
    tracker = CursorTracker(access_token=None)
    with patch.object(tracker, "_discover_token_from_sqlite", return_value=None):
        status = tracker.get_status()
        assert status.is_active is False
        assert status.used_percent == 0.0
        assert "Unconfigured" in status.status_label
        assert status.error is not None


def test_cursor_discover_token_from_sqlite(tmp_path: Path):
    db_file = tmp_path / "state.vscdb"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("INSERT INTO ItemTable VALUES ('cursorAuth/accessToken', '\"secret-cursor-jwt\"')")
    conn.commit()
    conn.close()

    tracker = CursorTracker(db_path=db_file)
    discovered = tracker._discover_token_from_sqlite()
    assert discovered == "secret-cursor-jwt"


def test_cursor_poke():
    tracker = CursorTracker()
    with patch("shutil.which", return_value="/bin/cursor"):
        mock_proc = MagicMock(returncode=0, stdout="0.41.2\n")
        with patch("subprocess.run", return_value=mock_proc):
            res = tracker.poke()
            assert res.action_taken == "poked"
            assert "0.41.2" in res.message


# ==============================================================================
# Windsurf Tracker Tests
# ==============================================================================

def test_windsurf_status_with_mock_api():
    tracker = WindsurfTracker(api_key="codeium-key-xyz")
    mock_data = {
        "user": {
            "plan_type": "Pro",
            "used_percent": 42.5,
        }
    }

    with patch.object(tracker, "_query_status_api", return_value=(mock_data, None)):
        status = tracker.get_status()
        assert status.provider == "windsurf"
        assert status.is_active is True
        assert status.used_percent == 42.5
        assert status.status_label == "Active"
        assert status.details["plan"] == "Pro"


def test_windsurf_status_unconfigured():
    tracker = WindsurfTracker(api_key=None)
    with patch.object(tracker, "_discover_api_key", return_value=None):
        status = tracker.get_status()
        assert status.is_active is False
        assert status.used_percent == 0.0
        assert "Unconfigured" in status.status_label


def test_windsurf_poke():
    tracker = WindsurfTracker()
    with patch("shutil.which", return_value="/usr/local/bin/windsurf"):
        mock_proc = MagicMock(returncode=0, stdout="1.2.0\n")
        with patch("subprocess.run", return_value=mock_proc):
            res = tracker.poke()
            assert res.action_taken == "poked"
            assert "1.2.0" in res.message


# ==============================================================================
# GitHub Copilot Tracker Tests
# ==============================================================================

def test_copilot_status_active():
    tracker = CopilotTracker(token="gho_mock_token")
    exp_ts = int((datetime.now(timezone.utc) + timedelta(hours=2)).timestamp())
    mock_data = {
        "token": "tid_xyz",
        "expires_at": exp_ts,
        "sku": "copilot_business",
        "chat_enabled": True,
    }

    with patch.object(tracker, "_query_copilot_token_api", return_value=(mock_data, None)):
        status = tracker.get_status()
        assert status.provider == "copilot"
        assert status.is_active is True
        assert status.status_label == "Active"
        assert status.time_remaining_seconds > 0
        assert "h" in status.time_remaining_str or "m" in status.time_remaining_str
        assert status.details["sku"] == "copilot_business"


def test_copilot_status_unconfigured():
    tracker = CopilotTracker(token=None)
    with patch.object(tracker, "_discover_token", return_value=None):
        status = tracker.get_status()
        assert status.is_active is False
        assert "Unconfigured" in status.status_label


def test_copilot_poke():
    tracker = CopilotTracker(token="gho_mock")
    with patch("shutil.which", return_value="/bin/gh"):
        mock_proc = MagicMock(returncode=0, stdout="github-copilot version 1.0.5\n")
        with patch("subprocess.run", return_value=mock_proc):
            res = tracker.poke()
            assert res.action_taken == "poked"
            assert "1.0.5" in res.message


# ==============================================================================
# Aider / OpenRouter Tracker Tests
# ==============================================================================

def test_aider_status_with_limit():
    tracker = AiderTracker(api_key="sk-or-v1-abc")
    mock_data = {
        "data": {
            "label": "My Coding Key",
            "usage": 20.0,
            "limit": 100.0,
            "is_free_tier": False,
        }
    }

    with patch.object(tracker, "_query_openrouter_api", return_value=(mock_data, None)):
        status = tracker.get_status()
        assert status.provider == "aider"
        assert status.is_active is True
        assert status.used_percent == 20.0
        assert status.weekly_used_percent == 20.0
        assert status.details["remaining_usd"] == 80.0
        assert status.details["label"] == "My Coding Key"


def test_aider_status_unconfigured():
    tracker = AiderTracker(api_key=None)
    with patch.object(tracker, "_discover_api_key", return_value=None):
        status = tracker.get_status()
        assert status.is_active is False
        assert "Unconfigured" in status.status_label


def test_aider_poke():
    tracker = AiderTracker()
    with patch("shutil.which", return_value="/bin/aider"):
        mock_proc = MagicMock(returncode=0, stdout="aider 0.58.0\n")
        with patch("subprocess.run", return_value=mock_proc):
            res = tracker.poke()
            assert res.action_taken == "poked"
            assert "0.58.0" in res.message
