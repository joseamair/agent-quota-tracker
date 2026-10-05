from __future__ import annotations

from agent_quota_tracker.metrics import render_prometheus_metrics
from agent_quota_tracker.models import AgentStatus


def test_render_empty_metrics():
    output = render_prometheus_metrics([])
    assert "agent_quota_tracker_up 1" in output
    assert "# HELP agent_quota_used_percent" in output
    assert "# TYPE agent_quota_used_percent gauge" in output
    assert output.endswith("\n")


def test_render_prometheus_metrics_with_agent_status():
    statuses = [
        AgentStatus(
            id="agy",
            name='Google "Antigravity" (AGY)',
            provider="agy",
            is_active=True,
            used_percent=42.5,
            weekly_used_percent=15.0,
            time_remaining_seconds=7200,
            category="personal",
            auth_status="valid",
        ),
        AgentStatus(
            id="claude-work",
            name="Claude (Work)",
            provider="claude",
            is_active=False,
            used_percent=0.0,
            weekly_used_percent=95.5,
            time_remaining_seconds=0,
            category="work",
            auth_status="expired",
        ),
    ]

    output = render_prometheus_metrics(statuses)

    # Tracker up
    assert "agent_quota_tracker_up 1" in output

    # Label escaping: double quotes escaped
    assert 'agent_name="Google \\"Antigravity\\" (AGY)"' in output

    # Quota used percent
    assert 'agent_quota_used_percent{agent_id="agy",agent_name="Google \\"Antigravity\\" (AGY)",provider="agy",category="personal"} 42.5' in output
    assert 'agent_quota_used_percent{agent_id="claude-work",agent_name="Claude (Work)",provider="claude",category="work"} 0.0' in output

    # Weekly used percent
    assert 'agent_weekly_used_percent{agent_id="agy",agent_name="Google \\"Antigravity\\" (AGY)",provider="agy",category="personal"} 15.0' in output
    assert 'agent_weekly_used_percent{agent_id="claude-work",agent_name="Claude (Work)",provider="claude",category="work"} 95.5' in output

    # Remaining fraction
    assert 'agent_quota_remaining_fraction{agent_id="agy",agent_name="Google \\"Antigravity\\" (AGY)",provider="agy",category="personal"} 0.5750' in output
    assert 'agent_quota_remaining_fraction{agent_id="claude-work",agent_name="Claude (Work)",provider="claude",category="work"} 1.0000' in output

    # Time remaining seconds
    assert 'agent_time_remaining_seconds{agent_id="agy",agent_name="Google \\"Antigravity\\" (AGY)",provider="agy",category="personal"} 7200' in output
    assert 'agent_time_remaining_seconds{agent_id="claude-work",agent_name="Claude (Work)",provider="claude",category="work"} 0' in output

    # Is active gauge
    assert 'agent_is_active{agent_id="agy",agent_name="Google \\"Antigravity\\" (AGY)",provider="agy",category="personal"} 1' in output
    assert 'agent_is_active{agent_id="claude-work",agent_name="Claude (Work)",provider="claude",category="work"} 0' in output

    # Auth valid gauge
    assert 'agent_auth_valid{agent_id="agy",agent_name="Google \\"Antigravity\\" (AGY)",provider="agy",category="personal"} 1' in output
    assert 'agent_auth_valid{agent_id="claude-work",agent_name="Claude (Work)",provider="claude",category="work"} 0' in output


def test_render_prometheus_metrics_with_dict():
    dicts = [
        {
            "id": "codex",
            "name": "OpenAI Codex",
            "provider": "codex",
            "category": "personal",
            "is_active": True,
            "used_percent": 10.0,
            "weekly_used_percent": None,
            "time_remaining_seconds": 1200,
            "auth_status": "valid",
        }
    ]

    output = render_prometheus_metrics(dicts)
    assert 'agent_quota_used_percent{agent_id="codex",agent_name="OpenAI Codex",provider="codex",category="personal"} 10.0' in output
    assert 'agent_weekly_used_percent{agent_id="codex",agent_name="OpenAI Codex",provider="codex",category="personal"} 0.0' in output
    assert 'agent_is_active{agent_id="codex",agent_name="OpenAI Codex",provider="codex",category="personal"} 1' in output
    assert 'agent_auth_valid{agent_id="codex",agent_name="OpenAI Codex",provider="codex",category="personal"} 1' in output
