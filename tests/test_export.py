from __future__ import annotations

import csv
import io
import time
from pathlib import Path

from agent_quota_tracker.history import (
    export_pokes_csv,
    export_snapshots_csv,
    init_db,
    record_poke,
    record_snapshots,
)
from agent_quota_tracker.models import AgentStatus


def test_export_empty_snapshots(tmp_path: Path):
    db_file = tmp_path / "test_history.db"
    csv_text = export_snapshots_csv(db_path=db_file)
    reader = list(csv.reader(io.StringIO(csv_text)))
    assert len(reader) == 1  # Only header
    assert reader[0] == [
        "timestamp_iso",
        "timestamp",
        "agent_id",
        "agent_name",
        "provider",
        "is_active",
        "used_percent",
        "weekly_used_percent",
        "time_remaining_seconds",
    ]


def test_export_snapshots_with_data(tmp_path: Path):
    db_file = tmp_path / "test_history.db"
    statuses = [
        AgentStatus(
            id="agy",
            name="Google Antigravity (AGY)",
            provider="agy",
            is_active=True,
            used_percent=25.0,
            weekly_used_percent=10.0,
            time_remaining_seconds=3600,
        ),
        AgentStatus(
            id="codex",
            name="OpenAI Codex",
            provider="codex",
            is_active=False,
            used_percent=0.0,
            weekly_used_percent=None,
            time_remaining_seconds=0,
        ),
    ]
    record_snapshots(statuses, db_path=db_file)

    out_file = tmp_path / "exported_snapshots.csv"
    csv_text = export_snapshots_csv(filepath=out_file, db_path=db_file)
    assert out_file.exists()
    assert out_file.read_text(encoding="utf-8") == csv_text

    reader = list(csv.reader(io.StringIO(csv_text)))
    assert len(reader) == 3  # Header + 2 rows
    assert reader[1][2] == "agy"
    assert reader[1][5] == "1"
    assert float(reader[1][6]) == 25.0
    assert float(reader[1][7]) == 10.0
    assert int(reader[1][8]) == 3600

    assert reader[2][2] == "codex"
    assert reader[2][5] == "0"
    assert float(reader[2][6]) == 0.0
    assert reader[2][7] == ""


def test_export_empty_pokes(tmp_path: Path):
    db_file = tmp_path / "test_history.db"
    csv_text = export_pokes_csv(db_path=db_file)
    reader = list(csv.reader(io.StringIO(csv_text)))
    assert len(reader) == 1
    assert reader[0] == [
        "timestamp_iso",
        "timestamp",
        "agent_id",
        "agent_name",
        "action",
        "message",
    ]


def test_export_pokes_with_data(tmp_path: Path):
    db_file = tmp_path / "test_history.db"
    record_poke(
        agent_id="claude-personal",
        agent_name="Claude (Personal)",
        action="poked",
        message="Window successfully verified active",
        db_path=db_file,
    )

    out_file = tmp_path / "exported_pokes.csv"
    csv_text = export_pokes_csv(filepath=out_file, db_path=db_file)
    assert out_file.exists()
    assert out_file.read_text(encoding="utf-8") == csv_text

    reader = list(csv.reader(io.StringIO(csv_text)))
    assert len(reader) == 2  # Header + 1 row
    assert reader[1][2] == "claude-personal"
    assert reader[1][4] == "poked"
    assert "verified active" in reader[1][5]


def test_export_days_filter(tmp_path: Path):
    db_file = tmp_path / "test_history.db"
    init_db(db_file)

    # Insert old record (10 days ago) and recent record
    import sqlite3
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    old_ts = time.time() - (10 * 86400)
    cur.execute(
        """
        INSERT INTO snapshots (
            timestamp, timestamp_iso, agent_id, agent_name, provider,
            is_active, used_percent, weekly_used_percent, time_remaining_seconds
        ) VALUES (?, '2026-01-01T00:00:00', 'agy', 'AGY', 'agy', 1, 50.0, NULL, 0)
        """,
        (old_ts,),
    )
    conn.commit()
    conn.close()

    # Filter with days=7 should exclude 10-day-old record
    csv_7d = export_snapshots_csv(days=7, db_path=db_file)
    rows_7d = list(csv.reader(io.StringIO(csv_7d)))
    assert len(rows_7d) == 1  # Only header

    # Filter with days=14 should include it
    csv_14d = export_snapshots_csv(days=14, db_path=db_file)
    rows_14d = list(csv.reader(io.StringIO(csv_14d)))
    assert len(rows_14d) == 2
