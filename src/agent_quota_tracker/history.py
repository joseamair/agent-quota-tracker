from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

_custom_db_path: Optional[Path] = None


def set_custom_db_path(path: Optional[Path]) -> None:
    global _custom_db_path
    _custom_db_path = path


def get_history_db_path(db_path: Optional[Path] = None) -> Path:
    if db_path is not None:
        return db_path
    if _custom_db_path is not None:
        return _custom_db_path
    d = Path(os.path.expanduser("~")) / ".agent_quota_tracker"
    d.mkdir(parents=True, exist_ok=True)
    return d / "history.db"


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target = get_history_db_path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                timestamp_iso TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                provider TEXT NOT NULL,
                is_active INTEGER NOT NULL,
                used_percent REAL NOT NULL,
                weekly_used_percent REAL,
                time_remaining_seconds INTEGER DEFAULT 0
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_agent_ts ON snapshots (agent_id, timestamp);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots (timestamp);")

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pokes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                timestamp_iso TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                action TEXT NOT NULL,
                message TEXT
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pokes_agent_ts ON pokes (agent_id, timestamp);")
        conn.commit()
    finally:
        conn.close()


def record_snapshots(statuses: list[Any], db_path: Optional[Path] = None) -> None:
    if not statuses:
        return
    init_db(db_path)
    now_ts = time.time()
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        for s in statuses:
            if isinstance(s, dict):
                aid = s.get("id") or s.get("agent_id")
                name = s.get("name") or s.get("display_name") or aid
                prov = s.get("provider") or "unknown"
                is_active = bool(s.get("is_active", False))
                used_pct = float(s.get("used_percent", 0.0))
                wk_pct = s.get("weekly_used_percent")
                wk_pct = float(wk_pct) if wk_pct is not None else None
                rem_secs = int(s.get("time_remaining_seconds", 0))
            else:
                aid = getattr(s, "id", None) or getattr(s, "agent_id", None)
                name = getattr(s, "name", None) or getattr(s, "display_name", None) or aid
                prov = getattr(s, "provider", "unknown")
                is_active = bool(getattr(s, "is_active", False))
                used_pct = float(getattr(s, "used_percent", 0.0))
                wk_pct = getattr(s, "weekly_used_percent", None)
                wk_pct = float(wk_pct) if wk_pct is not None else None
                rem_secs = int(getattr(s, "time_remaining_seconds", 0))

            if not aid:
                continue

            # Deduplication: check last record for this agent within past 60s
            cur.execute(
                """
                SELECT timestamp, used_percent, is_active, weekly_used_percent
                FROM snapshots
                WHERE agent_id = ?
                ORDER BY timestamp DESC LIMIT 1
                """,
                (aid,),
            )
            last = cur.fetchone()
            if last:
                last_ts = float(last["timestamp"])
                last_used = float(last["used_percent"])
                last_act = bool(last["is_active"])
                last_wk = float(last["weekly_used_percent"]) if last["weekly_used_percent"] is not None else None
                # Skip duplicate if less than 60s and values identical
                if (now_ts - last_ts < 60) and (last_used == used_pct) and (last_act == is_active) and (last_wk == wk_pct):
                    continue

            cur.execute(
                """
                INSERT INTO snapshots (
                    timestamp, timestamp_iso, agent_id, agent_name, provider,
                    is_active, used_percent, weekly_used_percent, time_remaining_seconds
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (now_ts, now_iso, aid, name, prov, 1 if is_active else 0, used_pct, wk_pct, rem_secs),
            )
        conn.commit()
    finally:
        conn.close()


def record_poke(
    agent_id: str,
    agent_name: str,
    action: str,
    message: str = "",
    db_path: Optional[Path] = None,
) -> None:
    init_db(db_path)
    now_ts = time.time()
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO pokes (timestamp, timestamp_iso, agent_id, agent_name, action, message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (now_ts, now_iso, agent_id, agent_name, action, message),
        )
        conn.commit()
    finally:
        conn.close()


def get_history_points(
    agent_id: Optional[str] = None,
    hours: int = 168,
    db_path: Optional[Path] = None,
) -> list[dict[str, Any]]:
    init_db(db_path)
    cutoff = time.time() - (hours * 3600)
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        if agent_id:
            cur.execute(
                """
                SELECT timestamp, timestamp_iso, agent_id, agent_name, provider,
                       is_active, used_percent, weekly_used_percent, time_remaining_seconds
                FROM snapshots
                WHERE timestamp >= ? AND (agent_id = ? OR agent_id = ?)
                ORDER BY timestamp ASC
                """,
                (cutoff, agent_id, f"claude-{agent_id}"),
            )
        else:
            cur.execute(
                """
                SELECT timestamp, timestamp_iso, agent_id, agent_name, provider,
                       is_active, used_percent, weekly_used_percent, time_remaining_seconds
                FROM snapshots
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
                """,
                (cutoff,),
            )
        rows = cur.fetchall()
        return [
            {
                "timestamp": r["timestamp"],
                "timestamp_iso": r["timestamp_iso"],
                "agent_id": r["agent_id"],
                "agent_name": r["agent_name"],
                "provider": r["provider"],
                "is_active": bool(r["is_active"]),
                "used_percent": float(r["used_percent"]),
                "weekly_used_percent": float(r["weekly_used_percent"]) if r["weekly_used_percent"] is not None else None,
                "time_remaining_seconds": int(r["time_remaining_seconds"]),
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_analytics_summary(
    days: int = 7,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    init_db(db_path)
    cutoff = time.time() - (days * 86400)
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT timestamp, timestamp_iso, agent_id, agent_name, provider,
                   is_active, used_percent, weekly_used_percent
            FROM snapshots
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
            """,
            (cutoff,),
        )
        rows = cur.fetchall()

        cur.execute("SELECT COUNT(*) as cnt FROM pokes WHERE timestamp >= ?", (cutoff,))
        poke_cnt = cur.fetchone()["cnt"]

        total_snaps = len(rows)
        if total_snaps == 0:
            return {
                "total_snapshots": 0,
                "total_pokes": poke_cnt,
                "days_analyzed": days,
                "active_time_ratio": 0.0,
                "hourly_activity": {h: 0 for h in range(24)},
                "peak_hours": [],
                "peak_hours_str": "No activity recorded yet",
                "recommended_poke_time": "07:30",
                "recommendation_reason": "Default recommended morning priming time (no historical data yet)",
                "agent_stats": {},
            }

        # Calculate hourly activity: distribution of active instances across 24 hours
        hourly_counts: dict[int, int] = {h: 0 for h in range(24)}
        agent_max_used: dict[str, float] = {}
        agent_active_count: dict[str, int] = {}
        active_snapshots = 0

        for r in rows:
            dt = datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).astimezone()
            hour = dt.hour
            is_act = bool(r["is_active"])
            used = float(r["used_percent"])
            aid = r["agent_id"]

            if is_act or used > 0:
                hourly_counts[hour] += 1
                active_snapshots += 1

            agent_max_used[aid] = max(agent_max_used.get(aid, 0.0), used)
            if is_act:
                agent_active_count[aid] = agent_active_count.get(aid, 0) + 1

        active_ratio = round((active_snapshots / total_snaps) * 100.0, 1) if total_snaps > 0 else 0.0

        # Peak hours: top 3 hours with most activity
        sorted_hours = sorted(hourly_counts.items(), key=lambda kv: kv[1], reverse=True)
        peak_hours = [h for h, count in sorted_hours[:3] if count > 0]

        if peak_hours:
            peak_hours_formatted = [f"{h:02d}:00" for h in sorted(peak_hours)]
            peak_str = ", ".join(peak_hours_formatted)
        else:
            peak_str = "Evenly distributed / Idle"

        # Recommended morning poke time logic:
        # Find earliest hour between 06:00 and 12:00 that has activity
        morning_hours = [h for h in range(6, 12) if hourly_counts.get(h, 0) > 0]
        if morning_hours:
            first_morning_hour = min(morning_hours)
            # Recommend priming 90 minutes before the first active hour
            rec_target_mins = max(360, (first_morning_hour * 60) - 90)
            rec_h, rec_m = divmod(rec_target_mins, 60)
            rec_poke_time = f"{rec_h:02d}:{rec_m:02d}"
            rec_reason = f"Derived from historical first activity spike at {first_morning_hour:02d}:00 (priming 90m before aligns 5h reset at midday)"
        else:
            rec_poke_time = "07:30"
            rec_reason = "Standard strategic priming time (optimal for 09:00 AM work starts)"

        agent_stats = {
            aid: {
                "max_used_percent": agent_max_used.get(aid, 0.0),
                "active_snapshots": agent_active_count.get(aid, 0),
            }
            for aid in agent_max_used
        }

        return {
            "total_snapshots": total_snaps,
            "total_pokes": poke_cnt,
            "days_analyzed": days,
            "active_time_ratio": active_ratio,
            "hourly_activity": hourly_counts,
            "peak_hours": peak_hours,
            "peak_hours_str": peak_str,
            "recommended_poke_time": rec_poke_time,
            "recommendation_reason": rec_reason,
            "agent_stats": agent_stats,
        }
    finally:
        conn.close()


def normalize_agent_identity(raw_name: str) -> tuple[str, str, str]:
    """Returns (agent_id, agent_name, provider) for any agent identifier or display name."""
    cleaned = raw_name.strip()
    lower = cleaned.lower()

    if "antigravity" in lower or lower == "agy":
        return ("agy", "Google Antigravity (AGY)", "Google Antigravity")
    if "codex" in lower:
        return ("codex", "OpenAI Codex", "OpenAI Codex")
    if "work2" in lower:
        return ("claude-work2", "Claude (Work2)", "Anthropic Claude")
    if "work" in lower:
        return ("claude-work", "Claude (Work)", "Anthropic Claude")
    if "personal" in lower:
        return ("claude-personal", "Claude (Personal)", "Anthropic Claude")
    if "default" in lower:
        return ("claude-default", "Claude (Default)", "Anthropic Claude")
    if "cursor" in lower:
        return ("cursor", "Cursor Composer", "Cursor")
    if "windsurf" in lower or "cascade" in lower:
        return ("windsurf", "Windsurf / Cascade", "Windsurf")
    if "copilot" in lower:
        return ("copilot", "GitHub Copilot CLI", "GitHub Copilot")
    if "aider" in lower or "openrouter" in lower:
        return ("aider", "Aider / OpenRouter", "Aider")
    if "claude" in lower:
        return (f"claude-{lower.replace('claude', '').strip(' -_()')}", cleaned, "Anthropic Claude")

    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", lower)
    return (clean_id or "unknown", cleaned, "Unknown")


def backfill_history(
    log_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Backfills past poke activity and active window snapshots into SQLite history.db.

    Scans:
      1. ~/.agent_quota_tracker/schedule.log (timestamped logs of past morning priming & poke events)
      2. ~/.agents_dashboard/state.json (last_poked_at ISO timestamps per agent)

    Deduplicates all entries against existing database records; safe and idempotent to run repeatedly.
    """
    init_db(db_path)

    if log_path is None:
        log_path = Path(os.path.expanduser("~")) / ".agent_quota_tracker" / "schedule.log"
    if state_path is None:
        state_path = Path(os.path.expanduser("~")) / ".agents_dashboard" / "state.json"

    pokes_imported = 0
    snaps_imported = 0
    sources_used: list[str] = []

    conn = get_connection(db_path)
    try:
        cur = conn.cursor()

        # 1. Backfill from schedule.log
        if log_path.exists():
            sources_used.append(str(log_path))
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    m = re.match(
                        r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] Poke executed: (\d+) primed \((.*)\), (\d+) skipped",
                        line,
                    )
                    if not m:
                        continue
                    ts_str, count_str, primed_str, skipped_str = m.groups()
                    if primed_str.strip().lower() == "none":
                        continue

                    try:
                        # Parse timestamp as local datetime
                        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                        local_dt = dt.astimezone()
                        epoch_ts = local_dt.timestamp()
                        iso_ts = local_dt.isoformat()
                    except Exception:
                        continue

                    # Split agents by comma followed by capital letter or space
                    parts = [p.strip() for p in re.split(r",\s*(?=[A-Z])", primed_str) if p.strip()]
                    for agent_raw in parts:
                        aid, aname, prov = normalize_agent_identity(agent_raw)

                        # Deduplicate in pokes: within 60s
                        cur.execute(
                            "SELECT id FROM pokes WHERE agent_id = ? AND abs(timestamp - ?) < 60 LIMIT 1",
                            (aid, epoch_ts),
                        )
                        if not cur.fetchone():
                            cur.execute(
                                """
                                INSERT INTO pokes (timestamp, timestamp_iso, agent_id, agent_name, action, message)
                                VALUES (?, ?, ?, ?, 'primed', 'Backfilled from schedule.log')
                                """,
                                (epoch_ts, iso_ts, aid, aname),
                            )
                            pokes_imported += 1

                        # Deduplicate in snapshots: within 60s
                        cur.execute(
                            "SELECT id FROM snapshots WHERE agent_id = ? AND abs(timestamp - ?) < 60 LIMIT 1",
                            (aid, epoch_ts),
                        )
                        if not cur.fetchone():
                            cur.execute(
                                """
                                INSERT INTO snapshots (
                                    timestamp, timestamp_iso, agent_id, agent_name, provider,
                                    is_active, used_percent, weekly_used_percent, time_remaining_seconds
                                ) VALUES (?, ?, ?, ?, ?, 1, 0.0, NULL, 18000)
                                """,
                                (epoch_ts, iso_ts, aid, aname, prov),
                            )
                            snaps_imported += 1

        # 2. Backfill from state.json
        if state_path.exists():
            sources_used.append(str(state_path))
            try:
                with open(state_path, "r", encoding="utf-8", errors="replace") as f:
                    state_data = json.load(f)
                if isinstance(state_data, dict):
                    for agent_key, info in state_data.items():
                        if not isinstance(info, dict):
                            continue
                        last_poked_at = info.get("last_poked_at")
                        if not last_poked_at:
                            continue
                        try:
                            dt = datetime.fromisoformat(last_poked_at)
                            epoch_ts = dt.timestamp()
                            iso_ts = dt.isoformat()
                        except Exception:
                            continue

                        aid, aname, prov = normalize_agent_identity(agent_key)

                        cur.execute(
                            "SELECT id FROM pokes WHERE agent_id = ? AND abs(timestamp - ?) < 60 LIMIT 1",
                            (aid, epoch_ts),
                        )
                        if not cur.fetchone():
                            cur.execute(
                                """
                                INSERT INTO pokes (timestamp, timestamp_iso, agent_id, agent_name, action, message)
                                VALUES (?, ?, ?, ?, 'primed', 'Backfilled from state.json')
                                """,
                                (epoch_ts, iso_ts, aid, aname),
                            )
                            pokes_imported += 1

                        cur.execute(
                            "SELECT id FROM snapshots WHERE agent_id = ? AND abs(timestamp - ?) < 60 LIMIT 1",
                            (aid, epoch_ts),
                        )
                        if not cur.fetchone():
                            cur.execute(
                                """
                                INSERT INTO snapshots (
                                    timestamp, timestamp_iso, agent_id, agent_name, provider,
                                    is_active, used_percent, weekly_used_percent, time_remaining_seconds
                                ) VALUES (?, ?, ?, ?, ?, 1, 0.0, NULL, 18000)
                                """,
                                (epoch_ts, iso_ts, aid, aname, prov),
                            )
                            snaps_imported += 1
            except Exception:
                pass

        conn.commit()
    finally:
        conn.close()

    return {
        "success": True,
        "pokes_imported": pokes_imported,
        "snapshots_imported": snaps_imported,
        "sources": sources_used,
    }


def export_snapshots_csv(
    filepath: Optional[str | Path] = None,
    days: Optional[int] = None,
    agent_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> str:
    """Exports quota snapshot time-series data to CSV.

    If filepath is specified and not '-', writes output to that path.
    Always returns the generated CSV text.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        query = """
            SELECT timestamp_iso, timestamp, agent_id, agent_name, provider,
                   is_active, used_percent, weekly_used_percent, time_remaining_seconds
            FROM snapshots
        """
        params: list[Any] = []
        conditions: list[str] = []

        if days is not None and days > 0:
            cutoff = time.time() - (days * 86400)
            conditions.append("timestamp >= ?")
            params.append(cutoff)

        if agent_id:
            conditions.append("(agent_id = ? OR agent_id = ?)")
            params.extend([agent_id, f"claude-{agent_id}"])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp ASC"

        cur.execute(query, tuple(params))
        rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([
            "timestamp_iso",
            "timestamp",
            "agent_id",
            "agent_name",
            "provider",
            "is_active",
            "used_percent",
            "weekly_used_percent",
            "time_remaining_seconds",
        ])

        for r in rows:
            writer.writerow([
                r["timestamp_iso"],
                r["timestamp"],
                r["agent_id"],
                r["agent_name"],
                r["provider"],
                1 if r["is_active"] else 0,
                r["used_percent"],
                r["weekly_used_percent"] if r["weekly_used_percent"] is not None else "",
                r["time_remaining_seconds"],
            ])

        csv_text = output.getvalue()
        if filepath and str(filepath).strip() != "-":
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(csv_text, encoding="utf-8")

        return csv_text
    finally:
        conn.close()


def export_pokes_csv(
    filepath: Optional[str | Path] = None,
    days: Optional[int] = None,
    agent_id: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> str:
    """Exports historical poke action records to CSV.

    If filepath is specified and not '-', writes output to that path.
    Always returns the generated CSV text.
    """
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        cur = conn.cursor()
        query = """
            SELECT timestamp_iso, timestamp, agent_id, agent_name, action, message
            FROM pokes
        """
        params: list[Any] = []
        conditions: list[str] = []

        if days is not None and days > 0:
            cutoff = time.time() - (days * 86400)
            conditions.append("timestamp >= ?")
            params.append(cutoff)

        if agent_id:
            conditions.append("(agent_id = ? OR agent_id = ?)")
            params.extend([agent_id, f"claude-{agent_id}"])

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp ASC"

        cur.execute(query, tuple(params))
        rows = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow([
            "timestamp_iso",
            "timestamp",
            "agent_id",
            "agent_name",
            "action",
            "message",
        ])

        for r in rows:
            writer.writerow([
                r["timestamp_iso"],
                r["timestamp"],
                r["agent_id"],
                r["agent_name"],
                r["action"],
                r["message"] or "",
            ])

        csv_text = output.getvalue()
        if filepath and str(filepath).strip() != "-":
            p = Path(filepath)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(csv_text, encoding="utf-8")

        return csv_text
    finally:
        conn.close()

