from __future__ import annotations

import json
import threading
import time
import urllib.request
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent_quota_tracker.dashboard import (
    DashboardHandler,
    generate_html_file,
    HTML_TEMPLATE,
    _update_event,
)
from agent_quota_tracker.models import AgentStatus, PokeResult


def test_dashboard_html_template_contains_v2_features():
    assert "data-theme=\"oled\"" in HTML_TEMPLATE
    assert "data-theme=\"light\"" in HTML_TEMPLATE
    assert "EventSource('/api/stream')" in HTML_TEMPLATE
    assert "theme-switcher" in HTML_TEMPLATE
    assert "schedule-modal" in HTML_TEMPLATE
    assert "stream-indicator" in HTML_TEMPLATE
    assert "btn-poke-all" in HTML_TEMPLATE


def test_generate_html_file(tmp_path):
    out_file = tmp_path / "dashboard.html"
    res = generate_html_file(out_file)
    assert res.exists()
    content = res.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "AI Agents Quota Dashboard" in content


@pytest.fixture(scope="module")
def dashboard_test_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
    host, port = server.server_address
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    server.shutdown()
    server.server_close()


def test_get_index_html(dashboard_test_server):
    url = f"{dashboard_test_server}/"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        body = resp.read().decode("utf-8")
        assert "AI Agents Quota Dashboard" in body


def test_get_api_status(dashboard_test_server):
    dummy_status = AgentStatus(
        id="codex",
        name="OpenAI Codex",
        provider="codex",
        is_active=True,
        used_percent=12.5,
        time_remaining_seconds=3600,
        time_remaining_str="1h",
    )
    with patch("agent_quota_tracker.dashboard.get_all_statuses", return_value=[dummy_status]):
        url = f"{dashboard_test_server}/api/status"
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["id"] == "codex"
            assert data[0]["used_percent"] == 12.5


def test_get_api_schedule(dashboard_test_server):
    mock_status = {
        "status": "installed",
        "platform": "windows",
        "task_name": "AgentQuotaTrackerMorningPriming",
        "state": "Ready",
        "next_run_time": "2026-10-03 07:30:00",
    }
    with patch("agent_quota_tracker.dashboard.get_schedule_status", return_value=mock_status):
        url = f"{dashboard_test_server}/api/schedule"
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "installed"
            assert data["platform"] == "windows"
            assert data["next_run_time"] == "2026-10-03 07:30:00"


def test_post_api_poke(dashboard_test_server):
    mock_res = [
        PokeResult(
            agent_id="codex",
            agent_name="OpenAI Codex",
            action_taken="poked",
            message="Verified ACTIVE",
            verified_active=True,
        )
    ]
    with patch("agent_quota_tracker.dashboard.poke_all", return_value=mock_res) as mock_poke:
        url = f"{dashboard_test_server}/api/poke"
        payload = json.dumps({"agent_id": "codex", "force": True}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"
            assert len(data["results"]) == 1
            assert data["results"][0]["agent_id"] == "codex"
            mock_poke.assert_called_once_with(force=True, agent_id="codex")


def test_post_api_schedule_install(dashboard_test_server):
    mock_install_res = {
        "status": "installed",
        "platform": "windows",
        "time": "08:15",
    }
    with patch("agent_quota_tracker.dashboard.install_schedule", return_value=mock_install_res) as mock_inst:
        url = f"{dashboard_test_server}/api/schedule"
        payload = json.dumps({
            "action": "install",
            "time": "08:15",
            "frequency": "weekdays",
            "notify": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "installed"
            assert data["time"] == "08:15"
            mock_inst.assert_called_once_with(time_str="08:15", notify=False, frequency="weekdays")


def test_post_api_schedule_remove(dashboard_test_server):
    mock_rem_res = {"status": "removed"}
    with patch("agent_quota_tracker.dashboard.remove_schedule", return_value=mock_rem_res) as mock_rem:
        url = f"{dashboard_test_server}/api/schedule"
        payload = json.dumps({"action": "remove"}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "removed"
            mock_rem.assert_called_once()


def test_api_stream_sse_initial_chunk(dashboard_test_server):
    import http.client
    from urllib.parse import urlparse

    dummy_status = AgentStatus(
        id="agy",
        name="Google Antigravity (AGY)",
        provider="agy",
        is_active=True,
        used_percent=20.0,
    )

    with patch("agent_quota_tracker.dashboard.get_all_statuses", return_value=[dummy_status]):
        parsed = urlparse(dashboard_test_server)
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
        conn.request("GET", "/api/stream")
        resp = conn.getresponse()
        assert resp.status == 200
        assert "text/event-stream" in resp.getheader("Content-Type", "")

        # Read the first event chunk
        chunk = resp.read(256).decode("utf-8", errors="replace")
        assert "event: quota_update" in chunk
        assert "agy" in chunk
        conn.close()


def test_get_api_history(dashboard_test_server):
    mock_history = [
        {
            "timestamp": 1700000000.0,
            "timestamp_iso": "2026-10-02T10:00:00Z",
            "agent_id": "codex",
            "agent_name": "OpenAI Codex",
            "provider": "codex",
            "is_active": True,
            "used_percent": 30.0,
            "weekly_used_percent": 15.0,
            "time_remaining_seconds": 3600,
        }
    ]
    with patch("agent_quota_tracker.dashboard.get_history_points", return_value=mock_history):
        url = f"{dashboard_test_server}/api/history?agent_id=codex&hours=24"
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert len(data) == 1
            assert data[0]["agent_id"] == "codex"
            assert data[0]["used_percent"] == 30.0


def test_get_api_analytics(dashboard_test_server):
    mock_analytics = {
        "total_snapshots": 10,
        "total_pokes": 2,
        "days_analyzed": 7,
        "active_time_ratio": 45.0,
        "peak_hours": [9, 14],
        "peak_hours_str": "09:00, 14:00",
        "recommended_poke_time": "07:30",
        "recommendation_reason": "Derived from morning peak",
        "hourly_activity": {str(h): 1 for h in range(24)},
        "agent_stats": {"codex": {"max_used_percent": 50.0, "active_snapshots": 5}},
    }
    with patch("agent_quota_tracker.dashboard.get_analytics_summary", return_value=mock_analytics):
        url = f"{dashboard_test_server}/api/analytics?days=7"
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["total_snapshots"] == 10
            assert data["active_time_ratio"] == 45.0
            assert data["recommended_poke_time"] == "07:30"

