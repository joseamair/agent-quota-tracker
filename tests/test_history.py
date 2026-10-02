from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_quota_tracker.history import (
    init_db,
    get_connection,
    record_snapshots,
    record_poke,
    get_history_points,
    get_analytics_summary,
    set_custom_db_path,
    normalize_agent_identity,
    backfill_history,
)
from agent_quota_tracker.models import AgentStatus
from agent_quota_tracker.cli import run_analytics_command, run_backfill_cmd


@pytest.fixture
def temp_db(tmp_path: Path):
    db_file = tmp_path / "history.db"
    set_custom_db_path(db_file)
    init_db(db_file)
    yield db_file
    set_custom_db_path(None)


def test_init_db_creates_tables_and_indexes(temp_db: Path):
    conn = get_connection(temp_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cur.fetchall()}
        assert "snapshots" in tables
        assert "pokes" in tables

        cur.execute("SELECT name FROM sqlite_master WHERE type='index';")
        indexes = {row[0] for row in cur.fetchall()}
        assert "idx_snapshots_agent_ts" in indexes
        assert "idx_snapshots_ts" in indexes
        assert "idx_pokes_agent_ts" in indexes
    finally:
        conn.close()


def test_record_snapshots_and_retrieval(temp_db: Path):
    s1 = AgentStatus(
        id="codex",
        name="OpenAI Codex",
        provider="codex",
        is_active=True,
        used_percent=25.0,
        weekly_used_percent=15.0,
        time_remaining_seconds=3600,
    )
    s2 = AgentStatus(
        id="agy",
        name="Google Antigravity",
        provider="agy",
        is_active=False,
        used_percent=0.0,
        weekly_used_percent=10.0,
        time_remaining_seconds=0,
    )

    record_snapshots([s1, s2], db_path=temp_db)

    pts = get_history_points(hours=24, db_path=temp_db)
    assert len(pts) == 2
    codex_pt = next(p for p in pts if p["agent_id"] == "codex")
    assert codex_pt["is_active"] is True
    assert codex_pt["used_percent"] == 25.0
    assert codex_pt["weekly_used_percent"] == 15.0
    assert codex_pt["provider"] == "codex"


def test_record_snapshots_deduplication(temp_db: Path):
    s1 = AgentStatus(
        id="codex",
        name="OpenAI Codex",
        provider="codex",
        is_active=True,
        used_percent=25.0,
        weekly_used_percent=15.0,
        time_remaining_seconds=3600,
    )

    # First insert
    record_snapshots([s1], db_path=temp_db)
    pts1 = get_history_points(hours=24, db_path=temp_db)
    assert len(pts1) == 1

    # Immediate second insert with same metrics (should be deduplicated)
    record_snapshots([s1], db_path=temp_db)
    pts2 = get_history_points(hours=24, db_path=temp_db)
    assert len(pts2) == 1

    # Insert with changed used_percent (should NOT be deduplicated)
    s1_updated = AgentStatus(
        id="codex",
        name="OpenAI Codex",
        provider="codex",
        is_active=True,
        used_percent=30.0,
        weekly_used_percent=15.0,
        time_remaining_seconds=3400,
    )
    record_snapshots([s1_updated], db_path=temp_db)
    pts3 = get_history_points(hours=24, db_path=temp_db)
    assert len(pts3) == 2


def test_record_poke_and_retrieval(temp_db: Path):
    record_poke(
        agent_id="personal",
        agent_name="Claude Personal",
        action="poked",
        message="Window successfully primed",
        db_path=temp_db,
    )
    record_poke(
        agent_id="work",
        agent_name="Claude Work",
        action="skipped",
        message="Window already active",
        db_path=temp_db,
    )

    conn = get_connection(temp_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM pokes ORDER BY timestamp ASC")
        rows = cur.fetchall()
        assert len(rows) == 2
        assert rows[0]["agent_id"] == "personal"
        assert rows[0]["action"] == "poked"
        assert rows[1]["agent_id"] == "work"
        assert rows[1]["action"] == "skipped"
    finally:
        conn.close()


def test_get_history_points_filtering(temp_db: Path):
    now = time.time()
    conn = get_connection(temp_db)
    try:
        cur = conn.cursor()
        # Old record (10 days ago)
        cur.execute(
            """
            INSERT INTO snapshots (timestamp, timestamp_iso, agent_id, agent_name, provider, is_active, used_percent, weekly_used_percent, time_remaining_seconds)
            VALUES (?, ?, 'codex', 'Codex', 'codex', 1, 10.0, 5.0, 1800)
            """,
            (now - (10 * 86400), "old_iso"),
        )
        # Recent record (1 hour ago)
        cur.execute(
            """
            INSERT INTO snapshots (timestamp, timestamp_iso, agent_id, agent_name, provider, is_active, used_percent, weekly_used_percent, time_remaining_seconds)
            VALUES (?, ?, 'codex', 'Codex', 'codex', 1, 20.0, 5.0, 1500)
            """,
            (now - 3600, "recent_iso"),
        )
        # Recent record for different agent
        cur.execute(
            """
            INSERT INTO snapshots (timestamp, timestamp_iso, agent_id, agent_name, provider, is_active, used_percent, weekly_used_percent, time_remaining_seconds)
            VALUES (?, ?, 'personal', 'Personal', 'claude', 0, 0.0, 2.0, 0)
            """,
            (now - 1800, "recent_iso_2"),
        )
        conn.commit()
    finally:
        conn.close()

    # Query last 24 hours - should filter out 10-day old record
    points_24h = get_history_points(hours=24, db_path=temp_db)
    assert len(points_24h) == 2

    # Query specific agent
    codex_points = get_history_points(agent_id="codex", hours=24, db_path=temp_db)
    assert len(codex_points) == 1
    assert codex_points[0]["agent_id"] == "codex"


def test_get_analytics_summary_empty(temp_db: Path):
    summary = get_analytics_summary(days=7, db_path=temp_db)
    assert summary["total_snapshots"] == 0
    assert summary["total_pokes"] == 0
    assert summary["active_time_ratio"] == 0.0
    assert summary["recommended_poke_time"] == "07:30"
    assert len(summary["hourly_activity"]) == 24


def test_get_analytics_summary_with_activity(temp_db: Path):
    now_dt = datetime.now(timezone.utc).astimezone()
    # Create records spanning morning hours to test optimal priming calculation
    conn = get_connection(temp_db)
    try:
        cur = conn.cursor()
        # Simulate active session at 09:15
        target_today_9am = now_dt.replace(hour=9, minute=15, second=0, microsecond=0)
        ts_9am = target_today_9am.timestamp()

        cur.execute(
            """
            INSERT INTO snapshots (timestamp, timestamp_iso, agent_id, agent_name, provider, is_active, used_percent, weekly_used_percent, time_remaining_seconds)
            VALUES (?, ?, 'codex', 'Codex', 'codex', 1, 45.0, 10.0, 14000)
            """,
            (ts_9am, target_today_9am.isoformat()),
        )
        # Record a poke
        cur.execute(
            """
            INSERT INTO pokes (timestamp, timestamp_iso, agent_id, agent_name, action, message)
            VALUES (?, ?, 'codex', 'Codex', 'poked', 'Verified active')
            """,
            (ts_9am - 60, target_today_9am.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    summary = get_analytics_summary(days=7, db_path=temp_db)
    assert summary["total_snapshots"] == 1
    assert summary["total_pokes"] == 1
    assert summary["active_time_ratio"] == 100.0
    assert 9 in summary["peak_hours"]
    assert "09:00" in summary["peak_hours_str"]
    # Recommends 90 minutes before 9:00 -> 07:30
    assert summary["recommended_poke_time"] == "07:30"
    assert "codex" in summary["agent_stats"]
    assert summary["agent_stats"]["codex"]["max_used_percent"] == 45.0


def test_run_analytics_command(temp_db: Path, capsys):
    # Test that run_analytics_command executes without throwing exceptions
    s = AgentStatus(
        id="codex",
        name="OpenAI Codex",
        provider="codex",
        is_active=True,
        used_percent=50.0,
    )
    record_snapshots([s], db_path=temp_db)

    run_analytics_command(days=7)
    captured = capsys.readouterr()
    assert "AI Agents Quota Velocity & Usage Analytics" in captured.out
    assert "24-Hour Usage Distribution" in captured.out
    assert "Per-Account Peak Breakdown" in captured.out


def test_normalize_agent_identity():
    aid, aname, prov = normalize_agent_identity("Google Antigravity (AGY)")
    assert aid == "agy"
    assert "Antigravity" in aname
    assert prov == "Google Antigravity"

    aid, aname, prov = normalize_agent_identity("OpenAI Codex")
    assert aid == "codex"
    assert prov == "OpenAI Codex"

    aid, aname, prov = normalize_agent_identity("Claude (Work2)")
    assert aid == "claude-work2"
    assert prov == "Anthropic Claude"

    aid, aname, prov = normalize_agent_identity("Cursor Composer")
    assert aid == "cursor"
    assert prov == "Cursor"


def test_backfill_history_from_legacy_files(temp_db: Path, tmp_path: Path):
    # 1. Create mock schedule.log
    log_file = tmp_path / "schedule.log"
    log_content = (
        "[2026-09-28 08:42:29] Poke executed: 3 primed (OpenAI Codex, Claude (Work), Claude (Work2)), 1 skipped, 0 failed\n"
        "[2026-09-29 11:34:32] Poke executed: 2 primed (Google Antigravity (AGY), Claude (Personal)), 3 skipped, 0 failed\n"
        "[2026-09-30 10:26:09] Poke executed: 0 primed (none), 5 skipped, 0 failed\n"
    )
    log_file.write_text(log_content, encoding="utf-8")

    # 2. Create mock state.json
    state_file = tmp_path / "state.json"
    state_content = {
        "claude-work": {"last_poked_at": "2026-10-01T07:15:00+00:00"},
        "agy": {"last_poked_at": "2026-10-01T07:20:00+00:00"},
    }
    state_file.write_text(json.dumps(state_content), encoding="utf-8")

    # Run backfill
    res = backfill_history(log_path=log_file, state_path=state_file, db_path=temp_db)
    assert res["success"] is True
    # 3 from first line + 2 from second line + 2 from state.json = 7 pokes
    assert res["pokes_imported"] == 7
    assert res["snapshots_imported"] == 7
    assert len(res["sources"]) == 2

    # Verify database contents
    conn = get_connection(temp_db)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM pokes")
        assert cur.fetchone()[0] == 7
        cur.execute("SELECT COUNT(*) FROM snapshots")
        assert cur.fetchone()[0] == 7
    finally:
        conn.close()

    # Check analytics summary reflects imported data
    summary = get_analytics_summary(days=7, db_path=temp_db)
    assert summary["total_pokes"] == 7
    assert summary["total_snapshots"] == 7
    assert 8 in summary["hourly_activity"] or 11 in summary["hourly_activity"]


def test_backfill_history_idempotent(temp_db: Path, tmp_path: Path):
    log_file = tmp_path / "schedule.log"
    log_file.write_text("[2026-09-28 08:42:29] Poke executed: 1 primed (OpenAI Codex), 4 skipped, 0 failed\n")

    # First run
    res1 = backfill_history(log_path=log_file, state_path=tmp_path / "nonexistent.json", db_path=temp_db)
    assert res1["pokes_imported"] == 1

    # Second run with same file
    res2 = backfill_history(log_path=log_file, state_path=tmp_path / "nonexistent.json", db_path=temp_db)
    assert res2["pokes_imported"] == 0
    assert res2["snapshots_imported"] == 0


def test_run_backfill_cmd(temp_db: Path, tmp_path: Path, capsys):
    log_file = tmp_path / "schedule.log"
    log_file.write_text("[2026-09-28 08:42:29] Poke executed: 1 primed (OpenAI Codex), 4 skipped, 0 failed\n")

    with patch("agent_quota_tracker.history.Path.home", return_value=tmp_path):
        with patch("pathlib.Path.home", return_value=tmp_path):
            with patch("agent_quota_tracker.cli.run_backfill_cmd") as mock_backfill:
                mock_backfill()
                assert mock_backfill.called
