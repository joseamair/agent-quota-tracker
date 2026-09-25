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


def parse_iso_datetime(dt_str: str) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        # Normalize 'Z' to '+00:00'
        cleaned = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class ClaudeTracker(BaseTracker):
    def __init__(self, profile_name: str, display_name: Optional[str] = None, category: str = "personal"):
        self.profile = profile_name
        self._display_name = display_name or f"Claude ({profile_name})"
        self._category = category
        self.home = Path(os.path.expanduser("~"))
        self.instance_dir = self.home / ".ccs" / "instances" / profile_name
        self.claude_json_path = self.instance_dir / ".claude.json"

    @property
    def agent_id(self) -> str:
        return f"claude-{self.profile}"

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def provider(self) -> str:
        return "claude"

    def _fetch_live_usage(self) -> Optional[dict[str, Any]]:
        try:
            creds_path = self.instance_dir / ".credentials.json"
            if not creds_path.exists():
                return None
            creds = json.loads(creds_path.read_text(encoding="utf-8"))
            token = creds.get("claudeAiOauth", {}).get("accessToken")
            if not token:
                return None

            import urllib.request
            req = urllib.request.Request(
                "https://api.anthropic.com/api/oauth/usage",
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "claude-code/2.1.281",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    # Update local .claude.json cache
                    try:
                        if self.claude_json_path.exists():
                            cj = json.loads(self.claude_json_path.read_text(encoding="utf-8"))
                            import time
                            cj["cachedUsageUtilization"] = {
                                "fetchedAtMs": int(time.time() * 1000),
                                "accountUuid": creds.get("claudeAiOauth", {}).get("accountUuid"),
                                "utilization": data,
                            }
                            self.claude_json_path.write_text(json.dumps(cj, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                    return data
        except Exception:
            pass
        return None

    def get_status(self) -> AgentStatus:
        agent_st = get_agent_state(self.agent_id)
        last_poked_at = agent_st.get("last_poked_at")

        live_data = self._fetch_live_usage()
        five_hour = {}
        seven_day = {}
        cached_usage = {}

        if live_data:
            five_hour = live_data.get("five_hour") or {}
            seven_day = live_data.get("seven_day") or {}
        elif self.claude_json_path.exists():
            try:
                raw_text = self.claude_json_path.read_text(encoding="utf-8")
                data = json.loads(raw_text)
                cached_usage = data.get("cachedUsageUtilization", {})
                utilization = cached_usage.get("utilization", {})
                five_hour = utilization.get("five_hour") or {}
                seven_day = utilization.get("seven_day") or {}
            except Exception as e:
                return AgentStatus(
                    id=self.agent_id,
                    name=self.display_name,
                    provider=self.provider,
                    is_active=False,
                    used_percent=0.0,
                    status_label="Error",
                    last_poked_at=last_poked_at,
                    error=f"Failed to read .claude.json: {e}",
                )
        else:
            return AgentStatus(
                id=self.agent_id,
                name=self.display_name,
                provider=self.provider,
                is_active=False,
                used_percent=0.0,
                status_label="Not initialized",
                last_poked_at=last_poked_at,
                error=f"Profile directory not found: {self.instance_dir}",
            )

        used_pct = float(five_hour.get("utilization") or 0.0)
        resets_at_str = five_hour.get("resets_at")
        resets_at_dt = parse_iso_datetime(resets_at_str) if resets_at_str else None

        now = datetime.now(timezone.utc)
        is_active = False
        remaining_seconds = 0

        # Check if idle:
        # Anthropic provides static prospective 5-hour time slots (resets_at)
        # even when an account has 0.0% utilization and has not been used.
        # It is only active if quota has been used or if a fresh poke occurred within 10 minutes.
        has_fresh_poke = False
        if last_poked_at:
            try:
                p_dt = parse_iso_datetime(last_poked_at)
                if p_dt and 0 <= (now - p_dt).total_seconds() < 600:
                    has_fresh_poke = True
            except Exception:
                pass

        is_idle = (used_pct == 0.0 and not has_fresh_poke)

        if resets_at_dt is not None and resets_at_dt > now and not is_idle:
            is_active = True
            remaining_seconds = max(0, int((resets_at_dt - now).total_seconds()))
            status_label = "Active"
        else:
            is_active = False
            remaining_seconds = 0
            status_label = "Inactive (Ready to Poke)"
            used_pct = 0.0
            resets_at_str = None
            resets_at_dt = None

        # Weekly stats
        weekly_used_pct = float(seven_day.get("utilization")) if seven_day.get("utilization") is not None else None
        weekly_resets_at = seven_day.get("resets_at")
        weekly_hours, weekly_reset_str = calculate_weekly_reset(weekly_resets_at)

        resets_at_ts = resets_at_dt.timestamp() if resets_at_dt else None

        return AgentStatus(
            id=self.agent_id,
            name=self.display_name,
            provider=self.provider,
            is_active=is_active,
            used_percent=used_pct,
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
            details={
                "profile": self.profile,
                "fetched_at_ms": cached_usage.get("fetchedAtMs") if cached_usage else None,
                "five_hour_raw": five_hour,
                "seven_day_raw": seven_day,
            },
        )

    def poke(self, prompt: str = "Hello, how are you doing?", force: bool = False) -> PokeResult:
        # Check current status first
        status = self.get_status()
        if status.is_active and not force:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="skipped",
                message=f"Window already active ({status.time_remaining_str} remaining, {status.used_percent}% used). Skipped poke.",
                time_remaining_str=status.time_remaining_str,
                used_percent=status.used_percent,
                verified_active=True,
            )

        ccs_bin = shutil.which("ccs") or shutil.which("ccs.cmd")
        if not ccs_bin:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="error",
                message="CCS command (ccs) not found in system PATH.",
            )

        # Run non-interactive print turn: ccs <profile> -p "<prompt>"
        cmd = [ccs_bin, self.profile, "-p", prompt]
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

            # Check new status locally (with retry up to 3 times)
            new_status = None
            for delay in (1.0, 2.0, 2.5):
                time.sleep(delay)
                new_status = self.get_status()
                if new_status.is_active:
                    break

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
                    message="Model replied, but 5h window did not register as active",
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
                message="Timed out after 45s waiting for CCS response.",
            )
        except Exception as e:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="error",
                message=f"Error executing poke: {e}",
            )
