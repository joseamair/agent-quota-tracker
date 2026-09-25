from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_quota_tracker.models import AgentStatus, PokeResult
from agent_quota_tracker.state import get_agent_state, update_agent_state
from agent_quota_tracker.trackers.base import (
    BaseTracker,
    calculate_weekly_reset,
    extract_reply_snippet,
    format_duration,
)


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        cleaned = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class AGYTracker(BaseTracker):
    _cached_quota: Optional[dict[str, Any]] = None
    _cached_quota_time: float = 0.0
    _CACHE_TTL: float = 10.0  # seconds

    def __init__(self, display_name: str = "Google Antigravity (AGY)", category: str = "personal"):
        self._display_name = display_name
        self._category = category
        self.home = Path(os.path.expanduser("~"))
        self.history_file = self.home / ".gemini" / "antigravity-cli" / "history.jsonl"
        self.window_duration_seconds = 5 * 3600  # 5 hours

    @property
    def agent_id(self) -> str:
        return "agy"

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def provider(self) -> str:
        return "AGY"

    def _fetch_live_quota(self, force: bool = False) -> Optional[dict[str, Any]]:
        now = time.time()
        if not force and AGYTracker._cached_quota and (now - AGYTracker._cached_quota_time < self._CACHE_TTL):
            return AGYTracker._cached_quota

        agy_bin = shutil.which("agy") or shutil.which("agy.exe")
        if not agy_bin:
            return None

        try:
            res = subprocess.run(
                [agy_bin, "-p", "/usage", "--output-format", "json"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout)
                cmd_data = data.get("command", {}).get("data", {})
                if cmd_data and "groups" in cmd_data:
                    AGYTracker._cached_quota = cmd_data
                    AGYTracker._cached_quota_time = now
                    return cmd_data
        except Exception:
            pass

        return None

    def _get_history_timestamp(self) -> tuple[Optional[float], int]:
        """Fallback helper: returns (latest_timestamp_seconds, count_in_last_5h)."""
        latest_ts = None
        count_in_5h = 0
        now_ts = time.time()

        if self.history_file.exists():
            try:
                lines = self.history_file.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                for line in reversed(lines):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts_ms = entry.get("timestamp")
                        if ts_ms:
                            ts_sec = float(ts_ms) / 1000.0
                            if latest_ts is None:
                                latest_ts = ts_sec
                            if now_ts - ts_sec < self.window_duration_seconds:
                                count_in_5h += 1
                            else:
                                break
                    except Exception:
                        continue
            except Exception:
                pass

        agent_st = get_agent_state(self.agent_id)
        last_poked_str = agent_st.get("last_poked_at")
        if last_poked_str:
            try:
                poked_dt = datetime.fromisoformat(last_poked_str.replace("Z", "+00:00"))
                poked_ts = poked_dt.timestamp()
                if latest_ts is None or poked_ts > latest_ts:
                    latest_ts = poked_ts
                if now_ts - poked_ts < self.window_duration_seconds:
                    count_in_5h = max(count_in_5h, 1)
            except Exception:
                pass

        return latest_ts, count_in_5h

    def get_status(self) -> AgentStatus:
        agent_st = get_agent_state(self.agent_id)
        last_poked_at = agent_st.get("last_poked_at")

        # 1. Try fetching authoritative live quota from AGY CLI (/usage)
        live_quota = self._fetch_live_quota()
        if live_quota and "groups" in live_quota:
            groups = live_quota.get("groups", [])
            gemini_group = next((g for g in groups if "gemini" in g.get("name", "").lower()), None)
            if not gemini_group and groups:
                gemini_group = groups[0]

            b_5h = None
            b_wk = None
            if gemini_group:
                for b in gemini_group.get("buckets", []):
                    win = b.get("window", "").lower()
                    bid = b.get("id", "").lower()
                    if win == "5h" or "5h" in bid:
                        b_5h = b
                    elif win == "weekly" or "weekly" in bid:
                        b_wk = b

            now = datetime.now(timezone.utc)

            is_active = False
            used_percent = 0.0
            remaining_seconds = 0
            resets_at_str = None
            resets_at_ts = None
            status_label = "Inactive (Ready to Poke)"

            if b_5h:
                rem_frac = float(b_5h.get("remaining_fraction", 1.0))
                used_pct = round(max(0.0, (1.0 - rem_frac) * 100), 1)
                r_time = b_5h.get("reset_time")
                r_dt = parse_iso_datetime(r_time)
                # Idle check: When AGY has 100% remaining quota (used_pct == 0.0),
                # its /usage API reports a prospective sliding reset_time = now + 5 hours.
                # It is only active if quota has been consumed (used_pct > 0)
                # or if a fresh poke was made within 10 minutes.
                has_fresh_poke = False
                if last_poked_at:
                    try:
                        p_dt = parse_iso_datetime(last_poked_at)
                        if p_dt and 0 <= (now - p_dt).total_seconds() < 600:
                            has_fresh_poke = True
                    except Exception:
                        pass

                is_idle = (used_pct == 0.0 and not has_fresh_poke)

                if r_dt and r_dt > now and not is_idle:
                    is_active = True
                    remaining_seconds = max(0, int((r_dt - now).total_seconds()))
                    resets_at_str = r_dt.isoformat()
                    resets_at_ts = r_dt.timestamp()
                    used_percent = used_pct
                    status_label = "Active"
                else:
                    is_active = False
                    used_percent = 0.0
                    remaining_seconds = 0
                    status_label = "Inactive (Ready to Poke)"
                    resets_at_str = None
                    resets_at_ts = None

            # Weekly quota
            weekly_used_pct = None
            weekly_resets_at = None
            weekly_hours = None
            weekly_reset_str = "-"

            if b_wk:
                wk_rem_frac = float(b_wk.get("remaining_fraction", 1.0))
                weekly_used_pct = round(max(0.0, (1.0 - wk_rem_frac) * 100), 1)
                weekly_resets_at = b_wk.get("reset_time")
                weekly_hours, weekly_reset_str = calculate_weekly_reset(weekly_resets_at)

            return AgentStatus(
                id=self.agent_id,
                name=self.display_name,
                provider=self.provider,
                is_active=is_active,
                used_percent=used_percent,
                resets_at=resets_at_str,
                resets_at_timestamp=resets_at_ts,
                time_remaining_seconds=remaining_seconds,
                time_remaining_str=format_duration(remaining_seconds) if is_active else "Inactive",
                window_duration_mins=300,
                status_label=status_label,
                weekly_used_percent=weekly_used_pct,
                weekly_resets_at=weekly_resets_at,
                weekly_remaining_hours=weekly_hours,
                weekly_reset_str=weekly_reset_str,
                category=self._category,
                last_poked_at=last_poked_at,
                details={"groups": groups},
            )

        # 2. Fallback to history.jsonl
        latest_activity_ts, count_in_5h = self._get_history_timestamp()
        now_ts = time.time()

        is_active = False
        remaining_seconds = 0
        resets_at_str = None
        resets_at_ts = None
        used_percent = 0.0

        if latest_activity_ts is not None:
            time_since_activity = now_ts - latest_activity_ts
            if time_since_activity < self.window_duration_seconds:
                is_active = True
                resets_at_ts = latest_activity_ts + self.window_duration_seconds
                remaining_seconds = max(0, int(resets_at_ts - now_ts))
                resets_dt = datetime.fromtimestamp(resets_at_ts, tz=timezone.utc)
                resets_at_str = resets_dt.isoformat()
                elapsed_pct = (time_since_activity / self.window_duration_seconds) * 100
                used_percent = round(min(100.0, elapsed_pct), 1)
                status_label = f"Active ({count_in_5h} reqs in window)"
            else:
                is_active = False
                remaining_seconds = 0
                status_label = "Inactive (Ready to Poke)"
                used_percent = 0.0
        else:
            status_label = "Inactive (No history)"
            used_percent = 0.0

        return AgentStatus(
            id=self.agent_id,
            name=self.display_name,
            provider=self.provider,
            is_active=is_active,
            used_percent=used_percent,
            resets_at=resets_at_str,
            resets_at_timestamp=resets_at_ts,
            time_remaining_seconds=remaining_seconds,
            time_remaining_str=format_duration(remaining_seconds) if is_active else "Inactive",
            window_duration_mins=300,
            status_label=status_label,
            category=self._category,
            last_poked_at=last_poked_at,
            details={
                "count_in_5h": count_in_5h,
                "latest_activity_ts": latest_activity_ts,
            },
        )

    def poke(self, prompt: str = "Hello, how are you doing?", force: bool = False) -> PokeResult:
        status = self.get_status()
        if status.is_active and not force:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="skipped",
                message=f"AGY 5h window already active ({status.time_remaining_str} remaining). Skipped poke.",
                time_remaining_str=status.time_remaining_str,
                used_percent=status.used_percent,
                verified_active=True,
            )

        agy_bin = shutil.which("agy") or shutil.which("agy.exe")
        if not agy_bin:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="error",
                message="AGY binary (agy) not found in PATH.",
            )

        cmd = [agy_bin, "-p", prompt, "--disable-slash-commands"]
        try:
            res = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
            )
            raw_out = (res.stdout or "").strip() or (res.stderr or "").strip()
            reply = extract_reply_snippet(raw_out)
            now_iso = datetime.now(timezone.utc).isoformat()
            update_agent_state(self.agent_id, {"last_poked_at": now_iso})

            # Invalidate cached quota to fetch fresh status
            AGYTracker._cached_quota = None
            AGYTracker._cached_quota_time = 0.0

            time.sleep(1.0)
            new_status = self.get_status()

            if new_status.is_active:
                return PokeResult(
                    agent_id=self.agent_id,
                    agent_name=self.display_name,
                    action_taken="poked",
                    message=f"Verified ACTIVE ({new_status.time_remaining_str} remaining, {new_status.used_percent}% used)",
                    reply=reply,
                    verified_active=True,
                    time_remaining_str=new_status.time_remaining_str,
                    used_percent=new_status.used_percent,
                    details=raw_out[:300],
                )
            else:
                return PokeResult(
                    agent_id=self.agent_id,
                    agent_name=self.display_name,
                    action_taken="unverified",
                    message="Model replied, but could not verify active window",
                    reply=reply,
                    verified_active=False,
                    time_remaining_str="Inactive",
                    used_percent=0.0,
                    details=raw_out[:300],
                )
        except subprocess.TimeoutExpired:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="error",
                message="Timed out after 45s waiting for AGY response.",
            )
        except Exception as e:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="error",
                message=f"Error executing agy poke: {e}",
            )
