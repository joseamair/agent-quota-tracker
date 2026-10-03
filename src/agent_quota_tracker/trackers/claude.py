from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
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
        self._display_name = display_name or (
            f"Claude ({profile_name})" if profile_name and profile_name not in ("default", "system") else "Claude"
        )
        self._category = category
        self.home = Path(os.path.expanduser("~"))
        if self.profile and self.profile not in ("default", "system"):
            self.instance_dir: Optional[Path] = self.home / ".ccs" / "instances" / profile_name
        else:
            self.instance_dir = None
        self.claude_json_path = (self.instance_dir / ".claude.json") if self.instance_dir else (self.home / ".claude.json")

    @property
    def agent_id(self) -> str:
        return f"claude-{self.profile}"

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def provider(self) -> str:
        return "claude"

    def _get_creds_path(self) -> Optional[Path]:
        """Finds credentials, checking CCS instance first, then standard Claude installation paths."""
        if self.instance_dir and self.instance_dir.exists():
            p = self.instance_dir / ".credentials.json"
            if p.exists() and p.is_file():
                return p
        # Fallback to standard Claude CLI locations (Windows / Linux / macOS)
        candidates = [
            self.home / ".claude" / ".credentials.json",
            self.home / ".claude.json",
            self.home / ".credentials.json",
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                return c
        return None

    def _get_json_path(self) -> Optional[Path]:
        """Finds cached .claude.json, checking CCS instance first, then standard path."""
        if self.instance_dir and self.instance_dir.exists():
            p = self.instance_dir / ".claude.json"
            if p.exists() and p.is_file():
                return p
        fallback = self.home / ".claude.json"
        if fallback.exists() and fallback.is_file():
            return fallback
        return None

    def _read_credentials(self) -> Optional[dict[str, Any]]:
        creds_path = self._get_creds_path()
        if not creds_path or not creds_path.exists():
            return None
        try:
            return json.loads(creds_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _read_claude_json(self) -> Optional[dict[str, Any]]:
        p = self._get_json_path() or self.claude_json_path
        if not p or not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _inspect_credentials(self) -> tuple[str, Optional[str]]:
        """Checks the local credentials file for existence, valid tokens, and expiration."""
        hint = (
            f"ccs {self.profile} login"
            if (self.profile and self.profile not in ("", "default", "system"))
            else "claude login"
        )
        creds = self._read_credentials()
        if not creds:
            return "missing", hint

        try:
            oauth = creds.get("claudeAiOauth", {})
            token = oauth.get("accessToken")
            if not token:
                return "missing", hint

            expires_at = oauth.get("expiresAt")
            if expires_at and isinstance(expires_at, (int, float)):
                # expiresAt is in milliseconds since epoch
                now_ms = time.time() * 1000
                if now_ms > expires_at:
                    return "expired", hint
        except Exception:
            return "missing", hint

        return "valid", None

    def _fetch_live_usage(self) -> Optional[dict[str, Any]]:
        self._http_auth_expired = False
        try:
            creds = self._read_credentials()
            if not creds:
                return None
            token = creds.get("claudeAiOauth", {}).get("accessToken")
            if not token:
                return None

            req = urllib.request.Request(
                "https://api.anthropic.com/api/oauth/usage",
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "claude-code/2.1.282",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    # Update local .claude.json cache
                    try:
                        target_json = self._get_json_path() or self.claude_json_path
                        if target_json and target_json.exists():
                            cj = json.loads(target_json.read_text(encoding="utf-8"))
                            cj["cachedUsageUtilization"] = {
                                "fetchedAtMs": int(time.time() * 1000),
                                "accountUuid": creds.get("claudeAiOauth", {}).get("accountUuid"),
                                "utilization": data,
                            }
                            target_json.write_text(json.dumps(cj, indent=2), encoding="utf-8")
                    except Exception:
                        pass
                    return data
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                self._http_auth_expired = True
        except Exception:
            pass
        return None

    def get_status(self) -> AgentStatus:
        agent_st = get_agent_state(self.agent_id)
        last_poked_at = agent_st.get("last_poked_at")

        auth_status, remediation_hint = self._inspect_credentials()
        live_data = self._fetch_live_usage()
        if getattr(self, "_http_auth_expired", False):
            auth_status = "expired"
            if not remediation_hint:
                remediation_hint = (
                    f"ccs {self.profile} login"
                    if (self.profile and self.profile not in ("", "default", "system"))
                    else "claude login"
                )
        elif live_data:
            auth_status = "valid"
            remediation_hint = None

        five_hour = {}
        seven_day = {}
        cached_usage = {}

        json_path = self._get_json_path()
        if live_data:
            five_hour = live_data.get("five_hour") or {}
            seven_day = live_data.get("seven_day") or {}
        elif json_path and json_path.exists():
            try:
                raw_text = json_path.read_text(encoding="utf-8")
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
                    auth_status=auth_status,
                    remediation_hint=remediation_hint,
                )
        else:
            status_lbl = "⚠️ EXPIRED" if auth_status == "expired" else "⚠️ NO AUTH"
            lock_msg = f"OAuth access token expired. Run '{remediation_hint}' to re-authenticate." if auth_status == "expired" else f"Claude credentials not found. Run '{remediation_hint}' to log in."
            return AgentStatus(
                id=self.agent_id,
                name=self.display_name,
                provider=self.provider,
                is_active=False,
                used_percent=0.0,
                status_label=status_lbl,
                last_poked_at=last_poked_at,
                error=f"Claude credentials or config not found for profile: {self.profile}",
                auth_status=auth_status,
                remediation_hint=remediation_hint,
                locked_reason=lock_msg,
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
        # It is only sliding idle if resets_at is sitting near the 5-hour ceiling (~300m)
        # without any token usage or fresh poke. If remaining_seconds < ~5h, the window
        # is already counting down and active.
        has_fresh_poke = False
        if last_poked_at:
            try:
                p_dt = parse_iso_datetime(last_poked_at)
                if p_dt and 0 <= (now - p_dt).total_seconds() < 600:
                    has_fresh_poke = True
            except Exception:
                pass

        remaining_secs = int((resets_at_dt - now).total_seconds()) if (resets_at_dt and resets_at_dt > now) else 0
        is_sliding_idle = (used_pct == 0.0 and not has_fresh_poke and remaining_secs >= (300 * 60 - 45))

        if resets_at_dt is not None and resets_at_dt > now and not is_sliding_idle:
            is_active = True
            remaining_seconds = remaining_secs
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

        # Locked reason
        locked_reason = five_hour.get("locked_reason") or seven_day.get("locked_reason")
        limits = (live_data.get("limits") or []) if live_data else []
        for lim in limits:
            if isinstance(lim, dict) and lim.get("severity") == "critical" and lim.get("percent", 0) >= 100:
                if not locked_reason:
                    locked_reason = "weekly_limit_exhausted"

        # Auth status overrides
        if auth_status == "expired":
            status_label = "⚠️ EXPIRED"
            if not locked_reason:
                locked_reason = f"OAuth access token expired. Run '{remediation_hint}' to re-authenticate."
        elif auth_status == "missing":
            if not status_label or status_label == "Inactive (Ready to Poke)":
                status_label = "⚠️ NO AUTH"
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
            locked_reason=locked_reason,
            auth_status=auth_status,
            remediation_hint=remediation_hint,
            details={
                "profile": self.profile,
                "fetched_at_ms": cached_usage.get("fetchedAtMs") if cached_usage else None,
                "five_hour_raw": five_hour,
                "seven_day_raw": seven_day,
                "locked_reason": locked_reason,
            },
        )

    def poke(self, prompt: str = "Hello, how are you doing?", force: bool = False) -> PokeResult:
        # Check current status first
        status = self.get_status()
        if not force and status.auth_status in ("expired", "missing"):
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="skipped",
                message=f"Authentication {status.auth_status} ({status.remediation_hint or 'Login required'}). Skipped poke (use --force to override).",
                time_remaining_str="Inactive",
                used_percent=status.used_percent,
                verified_active=False,
            )

        if status.is_active and not force:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="skipped",
                message=f"5h window is already active ({status.time_remaining_str} remaining, {status.used_percent}% used). Skipped poke.",
                time_remaining_str=status.time_remaining_str,
                used_percent=status.used_percent,
                verified_active=True,
            )

        if not force and isinstance(status.weekly_used_percent, (int, float)) and status.weekly_used_percent >= 100.0:
            reset_msg = f", resets in {status.weekly_remaining_hours:.1f}h" if status.weekly_remaining_hours is not None else ""
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="skipped",
                message=f"Weekly quota exhausted ({status.weekly_used_percent:.1f}% used{reset_msg}). Skipped poke (use --force to override).",
                time_remaining_str="Inactive",
                used_percent=status.used_percent,
                verified_active=False,
            )

        if not force and status.locked_reason:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="skipped",
                message=f"Account locked ({status.locked_reason}). Skipped poke (use --force to override).",
                time_remaining_str="Inactive",
                used_percent=status.used_percent,
                verified_active=False,
            )

        ccs_bin = shutil.which("ccs") or shutil.which("ccs.cmd")
        claude_bin = shutil.which("claude") or shutil.which("claude.exe") or shutil.which("claude.cmd")

        use_ccs = (
            bool(self.profile and self.profile not in ("", "default", "system"))
            and self.instance_dir is not None
            and self.instance_dir.exists()
            and ccs_bin is not None
        )

        if use_ccs:
            cmd = [ccs_bin, self.profile, "-p", prompt]
        elif claude_bin:
            cmd = [claude_bin, "-p", prompt]
        elif ccs_bin and self.profile:
            cmd = [ccs_bin, self.profile, "-p", prompt]
        else:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="error",
                message="Neither CCS (ccs) nor standard Claude CLI (claude) found in system PATH.",
            )
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
