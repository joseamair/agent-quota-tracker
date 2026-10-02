from __future__ import annotations

import os
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
