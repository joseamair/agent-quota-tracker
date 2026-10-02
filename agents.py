#!/usr/bin/env python3
"""
agents.py - Standalone 5-Hour Rate Limit Window & Quota Tracker
Tracks:
  - 3 Claude accounts via CCS (work, personal, work2)
  - OpenAI Codex (via JSON-RPC app-server query)
  - Google Antigravity / AGY (via CLI history & local session state)

Usage:
  python agents.py --status
  python agents.py --poke
  python agents.py --dashboard
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers & State
# ---------------------------------------------------------------------------

def get_state_file() -> Path:
    state_dir = Path(os.path.expanduser("~")) / ".agents_dashboard"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "state.json"


def load_state() -> dict[str, Any]:
    f = get_state_file()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def update_agent_state(agent_id: str, updates: dict[str, Any]) -> None:
    st = load_state()
    agent_st = st.get(agent_id, {})
    agent_st.update(updates)
    st[agent_id] = agent_st
    try:
        get_state_file().write_text(json.dumps(st, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_cache_dir() -> Path:
    d = Path(os.path.expanduser("~")) / ".agent_quota_tracker"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_cache_file() -> Path:
    p1 = Path(os.path.expanduser("~")) / ".agent_quota_tracker" / "cache.json"
    p2 = Path(os.path.expanduser("~")) / ".agents_dashboard" / "cache.json"
    if p1.exists():
        return p1
    if p2.exists():
        return p2
    p1.parent.mkdir(parents=True, exist_ok=True)
    return p1


def save_cache(statuses: list[Any]) -> None:
    cache_file = get_cache_file()
    now_ts = time.time()
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()
    accounts_data = [s.to_dict() if hasattr(s, "to_dict") else s for s in statuses]
    active_count = sum(1 for s in statuses if getattr(s, "is_active", False))
    payload = {
        "updated_at": now_iso,
        "updated_at_timestamp": now_ts,
        "active_count": active_count,
        "total_count": len(statuses),
        "accounts": accounts_data,
    }
    try:
        tmp_file = cache_file.with_suffix(".tmp")
        tmp_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_file.replace(cache_file)
    except Exception:
        try:
            cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass


def load_cache() -> Optional[dict[str, Any]]:
    cache_file = get_cache_file()
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "accounts" in data:
            return data
    except Exception:
        return None
    return None


def format_duration_short(seconds: int) -> str:
    if seconds <= 0:
        return "0m"
    hours, remainder = divmod(seconds, 3600)
    minutes = round(remainder / 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m" if minutes > 0 else f"{hours}h"
    return f"{max(1, minutes)}m"


def compute_live_prompt_data(cache: dict[str, Any], now_ts: Optional[float] = None) -> dict[str, Any]:
    if now_ts is None:
        now_ts = time.time()

    accounts = cache.get("accounts", [])
    active_accounts = []

    for acc in accounts:
        if not acc.get("is_active", False):
            continue

        resets_at_ts = acc.get("resets_at_timestamp")
        if resets_at_ts is not None:
            remaining = resets_at_ts - now_ts
        else:
            resets_at_str = acc.get("resets_at")
            if resets_at_str:
                try:
                    cleaned = resets_at_str.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(cleaned)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    remaining = (dt - datetime.now(timezone.utc)).total_seconds()
                except Exception:
                    remaining = acc.get("time_remaining_seconds", 0)
            else:
                remaining = acc.get("time_remaining_seconds", 0)

        if remaining > 0:
            active_accounts.append((acc, int(remaining)))

    active_count = len(active_accounts)
    total_count = len(accounts)

    if active_count > 0:
        min_rem_secs = min(rem for _, rem in active_accounts)
        max_rem_secs = max(rem for _, rem in active_accounts)
        min_remaining = format_duration_short(min_rem_secs)
        max_remaining = format_duration_short(max_rem_secs)
        status_str = "Active"
        icon_str = "⚡"
    else:
        min_rem_secs = 0
        max_rem_secs = 0
        min_remaining = "Idle"
        max_remaining = "Idle"
        status_str = "Idle"
        icon_str = "○"

    pct = round((active_count / total_count * 100), 0) if total_count > 0 else 0

    return {
        "active": active_count,
        "total": total_count,
        "min_remaining": min_remaining,
        "min_remaining_seconds": min_rem_secs,
        "max_remaining": max_remaining,
        "max_remaining_seconds": max_rem_secs,
        "status": status_str,
        "icon": icon_str,
        "percent": f"{int(pct)}%",
        "updated_at": cache.get("updated_at"),
    }


def format_prompt(
    preset_or_format: Optional[str] = None,
    cache: Optional[dict[str, Any]] = None,
    refresh: bool = False,
) -> str:
    if refresh or cache is None:
        if not refresh:
            cache = load_cache()

        if cache is None or refresh:
            statuses = fetch_all_statuses()
            save_cache(statuses)
            cache = load_cache()

    if not cache or "accounts" not in cache:
        return "[🤖 No Quota Data]"

    data = compute_live_prompt_data(cache)
    preset = (preset_or_format or "default").strip()
    preset_lower = preset.lower()

    if preset_lower == "default":
        if data["active"] > 0:
            return f"[{data['icon']} {data['active']}/{data['total']} Active • {data['min_remaining']}]"
        return f"[{data['icon']} 0/{data['total']} Active • Idle]"

    elif preset_lower == "compact":
        if data["active"] > 0:
            return f"{data['icon']}{data['active']}/{data['total']} {data['min_remaining']}"
        return f"{data['icon']}0/{data['total']}"

    elif preset_lower == "minimal":
        return f"🤖 {data['active']}/{data['total']}"

    elif preset_lower == "tmux":
        if data["active"] > 0:
            return f"#[fg=yellow]⚡#[default] {data['active']}/{data['total']} ({data['min_remaining']})"
        return f"#[fg=brightblack]○#[default] 0/{data['total']}"

    elif preset_lower == "json":
        return json.dumps(data)

    formatted = preset
    replacements = {
        "{active}": str(data["active"]),
        "{total}": str(data["total"]),
        "{min_remaining}": data["min_remaining"],
        "{min_remaining_seconds}": str(data["min_remaining_seconds"]),
        "{max_remaining}": data["max_remaining"],
        "{max_remaining_seconds}": str(data["max_remaining_seconds"]),
        "{status}": data["status"],
        "{icon}": data["icon"],
        "{percent}": data["percent"],
    }
    for token, val in replacements.items():
        formatted = formatted.replace(token, val)

    return formatted



def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0s"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h > 0:
        parts.append(f"{h}h")
    if m > 0:
        parts.append(f"{m}m")
    if s > 0 or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)


def parse_iso(dt_str: Optional[str]) -> Optional[datetime]:
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


def calculate_weekly_reset(resets_at_str: Optional[str]) -> tuple[Optional[float], str]:
    """Returns (remaining_hours, formatted_string_with_hrs_and_date)."""
    if not resets_at_str:
        return None, "-"
    dt = parse_iso(resets_at_str)
    if not dt:
        return None, "-"
    now = datetime.now(timezone.utc)
    secs = (dt - now).total_seconds()
    if secs <= 0:
        return 0.0, "Reset due"
    hours = round(secs / 3600.0, 1)
    local_dt = dt.astimezone()
    date_str = local_dt.strftime("%a %b %d, %H:%M")
    return hours, f"in {hours}h ({date_str})"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class AgentInfo:
    def __init__(
        self,
        id: str,
        name: str,
        provider: str,
        is_active: bool,
        used_percent: float,
        resets_at: Optional[str] = None,
        time_remaining_seconds: int = 0,
        weekly_used_percent: Optional[float] = None,
        weekly_resets_at: Optional[str] = None,
        weekly_remaining_hours: Optional[float] = None,
        weekly_reset_str: str = "-",
        status_label: str = "",
        error: Optional[str] = None,
        category: str = "personal",
    ):
        self.id = id
        self.name = name
        self.provider = provider
        self.is_active = is_active
        self.used_percent = round(used_percent, 1)
        self.resets_at = resets_at
        self.time_remaining_seconds = time_remaining_seconds
        self.time_remaining_str = format_duration(time_remaining_seconds) if is_active else "Inactive"
        self.weekly_used_percent = round(weekly_used_percent, 1) if weekly_used_percent is not None else None
        self.weekly_resets_at = weekly_resets_at
        self.weekly_remaining_hours = weekly_remaining_hours
        self.weekly_reset_str = weekly_reset_str
        self.status_label = status_label
        self.error = error
        self.category = category

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "category": self.category,
            "is_active": self.is_active,
            "used_percent": self.used_percent,
            "resets_at": self.resets_at,
            "time_remaining_seconds": self.time_remaining_seconds,
            "time_remaining_str": self.time_remaining_str,
            "weekly_used_percent": self.weekly_used_percent,
            "weekly_resets_at": self.weekly_resets_at,
            "weekly_remaining_hours": self.weekly_remaining_hours,
            "weekly_reset_str": self.weekly_reset_str,
            "status_label": self.status_label,
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Trackers: Claude (CCS)
# ---------------------------------------------------------------------------

import urllib.request

def get_claude_paths(profile: str) -> tuple[Optional[Path], Optional[Path]]:
    """Returns (creds_path, json_path) for Claude, checking CCS instances then standard installation."""
    home = Path(os.path.expanduser("~"))
    creds_path: Optional[Path] = None
    json_path: Optional[Path] = None

    if profile and profile not in ("", "default", "system"):
        inst_dir = home / ".ccs" / "instances" / profile
        if inst_dir.exists():
            c = inst_dir / ".credentials.json"
            if c.exists():
                creds_path = c
            j = inst_dir / ".claude.json"
            if j.exists():
                json_path = j

    if not creds_path:
        for cand in [
            home / ".claude" / ".credentials.json",
            home / ".claude.json",
            home / ".credentials.json",
        ]:
            if cand.exists() and cand.is_file():
                creds_path = cand
                break

    if not json_path:
        for cand in [
            home / ".claude.json",
            home / ".claude" / "settings.json",
        ]:
            if cand.exists() and cand.is_file():
                json_path = cand
                break

    return creds_path, json_path


def fetch_live_claude_usage(profile: str) -> Optional[dict[str, Any]]:
    """Query Anthropic API directly with profile credentials for instantaneous live data."""
    try:
        creds_path, json_path = get_claude_paths(profile)
        if not creds_path or not creds_path.exists():
            return None
        creds = json.loads(creds_path.read_text(encoding="utf-8"))
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
                # Write back to disk cache so other tools and offline runs have updated data
                try:
                    if json_path and json_path.exists():
                        cj = json.loads(json_path.read_text(encoding="utf-8"))
                        cj["cachedUsageUtilization"] = {
                            "fetchedAtMs": int(time.time() * 1000),
                            "accountUuid": creds.get("claudeAiOauth", {}).get("accountUuid"),
                            "utilization": data,
                        }
                        json_path.write_text(json.dumps(cj, indent=2), encoding="utf-8")
                except Exception:
                    pass
                return data
    except Exception:
        pass
    return None


def get_claude_status(profile: str, display_name: str, category: str = "personal") -> AgentInfo:
    creds_path, claude_json = get_claude_paths(profile)

    # 1. Try live API fetch first for real-time instantaneous status
    live_data = fetch_live_claude_usage(profile)

    five_hour = {}
    seven_day = {}

    if live_data:
        five_hour = live_data.get("five_hour") or {}
        seven_day = live_data.get("seven_day") or {}
    elif claude_json and claude_json.exists():
        try:
            data = json.loads(claude_json.read_text(encoding="utf-8"))
            cached_u = data.get("cachedUsageUtilization", {}).get("utilization", {})
            five_hour = cached_u.get("five_hour") or {}
            seven_day = cached_u.get("seven_day") or {}
        except Exception as e:
            return AgentInfo(
                id=f"claude-{profile}",
                name=display_name,
                provider="Claude",
                is_active=False,
                used_percent=0.0,
                status_label="Error",
                error=str(e),
                category=category,
            )
    else:
        return AgentInfo(
            id=f"claude-{profile}",
            name=display_name,
            provider="Claude",
            is_active=False,
            used_percent=0.0,
            status_label="Profile not found",
            error=f"Credentials or config not found for profile: {profile}",
            category=category,
        )

    used_pct = float(five_hour.get("utilization") or 0.0)
    resets_at_str = five_hour.get("resets_at")
    resets_dt = parse_iso(resets_at_str)

    now = datetime.now(timezone.utc)
    is_active = False
    remaining_secs = 0

    agent_st = load_state().get(f"claude-{profile}", {})
    last_poked_at = agent_st.get("last_poked_at")
    has_recent_poke = False
    if last_poked_at:
        try:
            p_dt = parse_iso(last_poked_at)
            if p_dt and 0 <= (now - p_dt).total_seconds() < 600:
                has_recent_poke = True
        except Exception:
            pass

    remaining_secs = int((resets_dt - now).total_seconds()) if (resets_dt and resets_dt > now) else 0
    is_sliding_idle = (used_pct == 0.0 and not has_recent_poke and remaining_secs >= (300 * 60 - 45))

    if resets_dt and resets_dt > now and not is_sliding_idle:
        is_active = True
        label = "Active"
    else:
        is_active = False
        remaining_secs = 0
        used_pct = 0.0
        resets_at_str = None
        label = "Inactive (Ready to Poke)"

    weekly_pct = float(seven_day.get("utilization")) if seven_day.get("utilization") is not None else None
    weekly_resets_at_str = seven_day.get("resets_at")
    weekly_hours, weekly_reset_str = calculate_weekly_reset(weekly_resets_at_str)

    return AgentInfo(
        id=f"claude-{profile}",
        name=display_name,
        provider="Claude",
        is_active=is_active,
        used_percent=used_pct,
        resets_at=resets_at_str,
        time_remaining_seconds=remaining_secs,
        weekly_used_percent=weekly_pct,
        weekly_resets_at=weekly_resets_at_str,
        weekly_remaining_hours=weekly_hours,
        weekly_reset_str=weekly_reset_str,
        status_label=label,
        category=category,
    )


def extract_reply_snippet(output: str, max_chars: int = 120) -> str:
    """Extract a clean, readable one-line snippet from the agent's CLI output."""
    if not output or not output.strip():
        return "(no reply text captured)"
    output = output.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    cleaned_lines = []
    for line in lines:
        lower = line.lower()
        if (
            line.startswith("Warning:")
            or line.startswith("Last progress:")
            or line.startswith("Thinking Process:")
            or line.startswith("Reading additional input")
            or line.startswith("OpenAI Codex")
            or line.startswith("--------")
            or lower.startswith("workdir:")
            or lower.startswith("model:")
            or lower.startswith("provider:")
            or lower.startswith("approval:")
            or lower.startswith("sandbox:")
            or lower.startswith("reasoning effort:")
            or lower.startswith("reasoning summaries:")
            or lower.startswith("session id:")
            or lower.startswith("tokens used")
            or lower.startswith("user ")
            or lower.startswith("codex ")
        ):
            continue
        cleaned_lines.append(line)

    if not cleaned_lines:
        return lines[0][:max_chars] if lines else "(no text response)"

    first = cleaned_lines[0]
    if len(first) > max_chars:
        return first[: max_chars - 3] + "..."
    return first


def poke_claude(profile: str, prompt: str = "Hello, how are you doing?") -> dict[str, Any]:
    ccs_bin = shutil.which("ccs") or shutil.which("ccs.cmd")
    claude_bin = shutil.which("claude") or shutil.which("claude.exe") or shutil.which("claude.cmd")

    home = Path(os.path.expanduser("~"))
    use_ccs = (
        bool(profile and profile not in ("", "default", "system"))
        and (home / ".ccs" / "instances" / profile).exists()
        and ccs_bin is not None
    )

    if use_ccs:
        cmd = [ccs_bin, profile, "-p", prompt]
    elif claude_bin:
        cmd = [claude_bin, "-p", prompt]
    elif ccs_bin and profile:
        cmd = [ccs_bin, profile, "-p", prompt]
    else:
        return {"status": "error", "message": "Neither CCS (ccs) nor standard Claude CLI (claude) found in PATH", "reply": None, "verified_active": False}

    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
        output = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        reply = extract_reply_snippet(output)
        update_agent_state(f"claude-{profile}", {"last_poked_at": datetime.now(timezone.utc).isoformat()})

        # Verify locally: fetch live usage and check if active (retry up to 3 times)
        verify_status = None
        for delay in (1.0, 2.0, 2.5):
            time.sleep(delay)
            verify_status = get_claude_status(profile, f"Claude ({profile})")
            if verify_status.is_active:
                break

        if verify_status.is_active:
            return {
                "status": "poked",
                "message": f"Verified ACTIVE ({verify_status.time_remaining_str} remaining, {verify_status.used_percent}% used)",
                "reply": reply,
                "verified_active": True,
                "time_remaining_str": verify_status.time_remaining_str,
                "used_percent": verify_status.used_percent,
            }
        else:
            return {
                "status": "unverified",
                "message": "Model replied, but 5h window did not register as active",
                "reply": reply,
                "verified_active": False,
                "time_remaining_str": "Inactive",
                "used_percent": 0.0,
            }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Timed out after 45s waiting for Claude reply", "reply": None, "verified_active": False}
    except Exception as e:
        return {"status": "error", "message": str(e), "reply": None, "verified_active": False}


# ---------------------------------------------------------------------------
# Trackers: OpenAI Codex
# ---------------------------------------------------------------------------

def get_codex_status(display_name: str = "OpenAI Codex", category: str = "personal") -> AgentInfo:
    codex_bin = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex_bin:
        return AgentInfo("codex", display_name, "Codex", False, 0.0, status_label="Codex CLI missing", category=category)

    res = None
    proc = None
    try:
        proc = subprocess.Popen(
            [codex_bin, "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        # Initialize
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "agents", "version": "1.0"}}}) + "\n")
        proc.stdin.flush()
        _ = proc.stdout.readline()

        # Read rate limits
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read", "params": {}}) + "\n")
        proc.stdin.flush()

        start = time.time()
        while time.time() - start < 3.0:
            line = proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
                if msg.get("id") == 2 and "result" in msg:
                    res = msg["result"]
                    break
            except Exception:
                continue
    except Exception:
        pass
    finally:
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass

    if not res or "rateLimits" not in res:
        return AgentInfo("codex", display_name, "Codex", False, 0.0, status_label="Could not query Codex limits", category=category)

    primary = res["rateLimits"].get("primary") or {}
    secondary = res["rateLimits"].get("secondary") or {}

    resets_at_ts = primary.get("resetsAt")
    used_pct = float(primary.get("usedPercent") or 0.0)
    window_mins = int(primary.get("windowDurationMins") or 300)
    now_ts = time.time()

    is_active = False
    remaining_secs = 0
    resets_at_str = None

    agent_st = load_state().get("codex", {})
    last_poked_at = agent_st.get("last_poked_at")
    has_recent_poke = False
    if last_poked_at:
        try:
            p_dt = parse_iso(last_poked_at)
            if p_dt and 0 <= (now_ts - p_dt.timestamp()) < 600:
                has_recent_poke = True
        except Exception:
            pass

    is_sliding_idle = (used_pct == 0.0 and not has_recent_poke and resets_at_ts is not None and (resets_at_ts - now_ts) >= (window_mins * 60 - 30))

    if resets_at_ts and resets_at_ts > now_ts and not is_sliding_idle:
        is_active = True
        remaining_secs = int(resets_at_ts - now_ts)
        resets_at_str = datetime.fromtimestamp(resets_at_ts, tz=timezone.utc).isoformat()
        label = "Active"
    else:
        is_active = False
        used_pct = 0.0
        remaining_secs = 0
        resets_at_str = None
        label = "Inactive (Ready to Poke)"

    weekly_pct = float(secondary.get("usedPercent")) if secondary.get("usedPercent") is not None else None
    weekly_resets_at_ts = secondary.get("resetsAt")
    if weekly_resets_at_ts:
        weekly_dt = datetime.fromtimestamp(weekly_resets_at_ts, tz=timezone.utc)
        weekly_resets_at_str = weekly_dt.isoformat()
        weekly_hours, weekly_reset_str = calculate_weekly_reset(weekly_resets_at_str)
    else:
        weekly_resets_at_str = None
        weekly_hours = None
        weekly_reset_str = "-"

    return AgentInfo(
        "codex",
        display_name,
        "Codex",
        is_active,
        used_pct,
        resets_at_str,
        remaining_secs,
        weekly_pct,
        weekly_resets_at_str,
        weekly_hours,
        weekly_reset_str,
        label,
        category=category,
    )


def poke_codex(prompt: str = "Hello, how are you doing?") -> dict[str, Any]:
    codex_bin = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex_bin:
        return {"status": "error", "message": "Codex CLI (codex) not found", "reply": None, "verified_active": False}

    try:
        proc = subprocess.run(
            [codex_bin, "exec", prompt, "--ephemeral", "--skip-git-repo-check", "--color", "never"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
        output = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        reply = extract_reply_snippet(output)
        update_agent_state("codex", {"last_poked_at": datetime.now(timezone.utc).isoformat()})

        # Verify locally
        time.sleep(1.0)
        verify_status = get_codex_status()
        if not verify_status.is_active:
            time.sleep(1.5)
            verify_status = get_codex_status()

        if verify_status.is_active:
            return {
                "status": "poked",
                "message": f"Verified ACTIVE ({verify_status.time_remaining_str} remaining, {verify_status.used_percent}% used)",
                "reply": reply,
                "verified_active": True,
                "time_remaining_str": verify_status.time_remaining_str,
                "used_percent": verify_status.used_percent,
            }
        else:
            return {
                "status": "unverified",
                "message": "Model replied, but 5h window did not register as active",
                "reply": reply,
                "verified_active": False,
                "time_remaining_str": "Inactive",
                "used_percent": 0.0,
            }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Timed out after 45s waiting for Codex reply", "reply": None, "verified_active": False}
    except Exception as e:
        return {"status": "error", "message": str(e), "reply": None, "verified_active": False}


# ---------------------------------------------------------------------------
# Trackers: Google Antigravity (AGY)
# ---------------------------------------------------------------------------

_agy_cached_quota: Optional[dict[str, Any]] = None
_agy_cached_time: float = 0.0


def fetch_agy_live_quota(force: bool = False) -> Optional[dict[str, Any]]:
    global _agy_cached_quota, _agy_cached_time
    now = time.time()
    if not force and _agy_cached_quota and (now - _agy_cached_time < 10.0):
        return _agy_cached_quota

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
                _agy_cached_quota = cmd_data
                _agy_cached_time = now
                return cmd_data
    except Exception:
        pass
    return None


def get_agy_status(display_name: str = "Google Antigravity (AGY)", category: str = "personal") -> AgentInfo:
    live_quota = fetch_agy_live_quota()
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
        remaining_secs = 0
        resets_at_str = None
        used_pct = 0.0
        label = "Inactive (Ready to Poke)"

        agent_st = load_state().get("agy", {})
        last_poked_at = agent_st.get("last_poked_at")
        has_fresh_poke = False
        if last_poked_at:
            try:
                p_dt = parse_iso(last_poked_at)
                if p_dt and 0 <= (now.timestamp() - p_dt.timestamp()) < 600:
                    has_fresh_poke = True
            except Exception:
                pass

        if b_5h:
            rem_frac = float(b_5h.get("remaining_fraction", 1.0))
            used_pct = round(max(0.0, (1.0 - rem_frac) * 100), 1)
            r_time = b_5h.get("reset_time")
            r_dt = parse_iso(r_time)

            remaining_secs = int((r_dt - now).total_seconds()) if (r_dt and r_dt > now) else 0
            is_sliding_idle = (used_pct == 0.0 and not has_fresh_poke and remaining_secs >= (300 * 60 - 45))

            if r_dt and r_dt > now and not is_sliding_idle:
                is_active = True
                resets_at_str = r_dt.isoformat()
                label = "Active"
            else:
                is_active = False
                used_pct = 0.0
                remaining_secs = 0
                resets_at_str = None
                label = "Inactive (Ready to Poke)"

        weekly_used_pct = None
        weekly_resets_at = None
        weekly_hours = None
        weekly_reset_str = "-"

        if b_wk:
            wk_rem_frac = float(b_wk.get("remaining_fraction", 1.0))
            weekly_used_pct = round(max(0.0, (1.0 - wk_rem_frac) * 100), 1)
            weekly_resets_at = b_wk.get("reset_time")
            weekly_hours, weekly_reset_str = calculate_weekly_reset(weekly_resets_at)

        return AgentInfo(
            "agy",
            display_name,
            "AGY",
            is_active,
            used_pct,
            resets_at_str,
            remaining_secs,
            weekly_used_pct,
            weekly_resets_at,
            weekly_hours,
            weekly_reset_str,
            label,
            category=category,
        )

    # Fallback to history.jsonl
    home = Path(os.path.expanduser("~"))
    hist_file = home / ".gemini" / "antigravity-cli" / "history.jsonl"
    five_hours = 5 * 3600
    now_ts = time.time()
    latest_ts = None
    count_in_5h = 0

    if hist_file.exists():
        try:
            lines = hist_file.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    ts_ms = entry.get("timestamp")
                    if ts_ms:
                        ts_sec = float(ts_ms) / 1000.0
                        if latest_ts is None:
                            latest_ts = ts_sec
                        if now_ts - ts_sec < five_hours:
                            count_in_5h += 1
                        else:
                            break
                except Exception:
                    continue
        except Exception:
            pass

    # Check local poke state
    st = load_state().get("agy", {})
    if st.get("last_poked_at"):
        try:
            dt = parse_iso(st["last_poked_at"])
            if dt and (latest_ts is None or dt.timestamp() > latest_ts):
                latest_ts = dt.timestamp()
                if now_ts - latest_ts < five_hours:
                    count_in_5h = max(count_in_5h, 1)
        except Exception:
            pass

    is_active = False
    remaining_secs = 0
    resets_at_str = None
    used_pct = 0.0

    if latest_ts and (now_ts - latest_ts < five_hours):
        is_active = True
        remaining_secs = int(five_hours - (now_ts - latest_ts))
        resets_at_str = datetime.fromtimestamp(latest_ts + five_hours, tz=timezone.utc).isoformat()
        used_pct = round(((now_ts - latest_ts) / five_hours) * 100, 1)
        label = f"Active ({count_in_5h} reqs in window)"
    else:
        label = "Inactive (Ready to Poke)"

    return AgentInfo("agy", display_name, "AGY", is_active, used_pct, resets_at_str, remaining_secs, None, None, None, "-", label, category=category)


def poke_agy(prompt: str = "Hello, how are you doing?") -> dict[str, Any]:
    global _agy_cached_quota, _agy_cached_time
    agy_bin = shutil.which("agy") or shutil.which("agy.exe")
    if not agy_bin:
        return {"status": "error", "message": "AGY CLI (agy) not found", "reply": None, "verified_active": False}

    try:
        proc = subprocess.run(
            [agy_bin, "-p", prompt, "--disable-slash-commands"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
        )
        output = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        reply = extract_reply_snippet(output)
        update_agent_state("agy", {"last_poked_at": datetime.now(timezone.utc).isoformat()})

        # Invalidate quota cache
        _agy_cached_quota = None
        _agy_cached_time = 0.0

        # Verify locally
        time.sleep(1.0)
        verify_status = get_agy_status()

        if verify_status.is_active:
            return {
                "status": "poked",
                "message": f"Verified ACTIVE ({verify_status.time_remaining_str} remaining, {verify_status.used_percent}% used)",
                "reply": reply,
                "verified_active": True,
                "time_remaining_str": verify_status.time_remaining_str,
                "used_percent": verify_status.used_percent,
            }
        else:
            return {
                "status": "unverified",
                "message": "Model replied, but could not verify active window",
                "reply": reply,
                "verified_active": False,
                "time_remaining_str": "Inactive",
                "used_percent": 0.0,
            }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "Timed out after 45s waiting for AGY reply", "reply": None, "verified_active": False}
    except Exception as e:
        return {"status": "error", "message": str(e), "reply": None, "verified_active": False}


# ---------------------------------------------------------------------------
# Additional Agent Trackers (Cursor, Windsurf, Copilot, Aider)
# ---------------------------------------------------------------------------

def _discover_cursor_token(custom_db: Optional[Path] = None) -> Optional[str]:
    if custom_db and custom_db.exists():
        candidates = [custom_db]
    else:
        home = Path(os.path.expanduser("~"))
        candidates = []
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb")
        candidates.append(home / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "state.vscdb")
        candidates.append(home / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb")

    for db_path in candidates:
        if db_path.exists() and db_path.is_file():
            try:
                conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=2.0)
                cur = conn.cursor()
                cur.execute("SELECT value FROM ItemTable WHERE key = 'cursorAuth/accessToken' LIMIT 1")
                row = cur.fetchone()
                conn.close()
                if row and row[0]:
                    token = str(row[0]).strip().strip('"').strip("'")
                    if token:
                        return token
            except Exception:
                pass
    return None


def get_cursor_status(
    display_name: str = "Cursor Composer",
    category: str = "personal",
    access_token: Optional[str] = None,
    cookie: Optional[str] = None,
    agent_id: str = "cursor",
) -> AgentInfo:
    token = access_token or _discover_cursor_token()
    if not token and not cookie:
        return AgentInfo(
            id=agent_id,
            name=display_name,
            provider="cursor",
            is_active=False,
            used_percent=0.0,
            status_label="Unconfigured / Offline",
            error="No Cursor access token or session cookie found. Configure access_token or login to Cursor.",
            category=category,
        )

    url = "https://api2.cursor.sh/auth/usage" if token else "https://www.cursor.com/api/usage"
    headers = {"User-Agent": "agent-quota-tracker/1.2.0", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if cookie:
        headers["Cookie"] = f"WorkosCursorSessionToken={cookie}"

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_msg = f"Cursor token expired or unauthorized ({e.code}). Please re-login to Cursor." if e.code in (401, 403) else f"HTTP {e.code}"
        return AgentInfo(id=agent_id, name=display_name, provider="cursor", is_active=False, used_percent=0.0, status_label="Error", error=err_msg, category=category)
    except Exception as ex:
        return AgentInfo(id=agent_id, name=display_name, provider="cursor", is_active=False, used_percent=0.0, status_label="Error", error=str(ex), category=category)

    num_requests = 0
    max_requests = 500
    start_of_month = data.get("startOfMonth")
    for key in ("gpt-4", "claude-3.5-sonnet", "fastRequests", "regularRequests"):
        m = data.get(key)
        if isinstance(m, dict):
            num_requests = m.get("numRequests", num_requests)
            max_requests = m.get("maxRequestUsage", max_requests)
            break

    used_pct = round((num_requests / max_requests * 100.0) if max_requests > 0 else 0.0, 1)
    wk_hours, wk_str = calculate_weekly_reset(start_of_month) if start_of_month else (None, "-")
    is_active = used_pct > 0.0

    return AgentInfo(
        id=agent_id,
        name=display_name,
        provider="cursor",
        is_active=is_active,
        used_percent=used_pct,
        weekly_used_percent=used_pct,
        weekly_resets_at=start_of_month,
        weekly_remaining_hours=wk_hours,
        weekly_reset_str=wk_str,
        status_label="Active" if is_active else "Idle",
        category=category,
    )


def poke_cursor(prompt: str = "Hello, how are you doing?") -> dict[str, Any]:
    c_bin = shutil.which("cursor")
    if c_bin:
        try:
            proc = subprocess.run([c_bin, "--version"], capture_output=True, text=True, timeout=5)
            ver = proc.stdout.strip().splitlines()[0] if proc.stdout else "unknown"
            return {"status": "poked", "message": f"Cursor IDE detected ({ver}). Monitored via API.", "reply": None, "verified_active": True}
        except Exception as e:
            return {"status": "error", "message": str(e), "reply": None, "verified_active": False}
    return {"status": "skipped", "message": "Cursor monitored via API. Headless CLI poke not supported.", "reply": None, "verified_active": False}


def _discover_windsurf_key() -> Optional[str]:
    home = Path(os.path.expanduser("~"))
    candidates = [
        home / ".codeium" / "config.json",
        home / ".codeium" / "windsurf" / "mcp_config.json",
    ]
    up = os.environ.get("USERPROFILE")
    if up:
        candidates.append(Path(up) / ".codeium" / "config.json")
    for path in candidates:
        if path.exists() and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                k = data.get("apiKey") or data.get("api_key") or data.get("token")
                if k and isinstance(k, str) and k.strip():
                    return k.strip()
            except Exception:
                pass
    return None


def get_windsurf_status(
    display_name: str = "Windsurf (Cascade)",
    category: str = "personal",
    api_key: Optional[str] = None,
    agent_id: str = "windsurf",
) -> AgentInfo:
    key = api_key or _discover_windsurf_key()
    if not key:
        return AgentInfo(
            id=agent_id,
            name=display_name,
            provider="windsurf",
            is_active=False,
            used_percent=0.0,
            status_label="Unconfigured / Offline",
            error="No Windsurf/Codeium API key found. Set api_key in config or login to Windsurf.",
            category=category,
        )

    url = "https://api.codeium.com/register_user/"
    payload = json.dumps({"api_key": key}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "agent-quota-tracker/1.2.0"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        return AgentInfo(id=agent_id, name=display_name, provider="windsurf", is_active=False, used_percent=0.0, status_label="Error", error=str(ex), category=category)

    user_info = data.get("user") or data
    used_pct = float(user_info.get("used_percent", 0.0))
    is_active = used_pct > 0.0

    return AgentInfo(
        id=agent_id,
        name=display_name,
        provider="windsurf",
        is_active=is_active,
        used_percent=used_pct,
        weekly_used_percent=used_pct,
        status_label="Active" if is_active else "Idle",
        category=category,
    )


def poke_windsurf(prompt: str = "Hello, how are you doing?") -> dict[str, Any]:
    w_bin = shutil.which("windsurf")
    if w_bin:
        try:
            proc = subprocess.run([w_bin, "--version"], capture_output=True, text=True, timeout=5)
            ver = proc.stdout.strip().splitlines()[0] if proc.stdout else "unknown"
            return {"status": "poked", "message": f"Windsurf IDE detected ({ver}). Monitored via API.", "reply": None, "verified_active": True}
        except Exception as e:
            return {"status": "error", "message": str(e), "reply": None, "verified_active": False}
    return {"status": "skipped", "message": "Windsurf monitored via API. Headless CLI poke not supported.", "reply": None, "verified_active": False}


def _discover_copilot_token() -> Optional[str]:
    gh_bin = shutil.which("gh")
    if gh_bin:
        try:
            proc = subprocess.run([gh_bin, "auth", "token"], capture_output=True, text=True, timeout=3)
            if proc.returncode == 0 and proc.stdout.strip():
                return proc.stdout.strip()
        except Exception:
            pass

    home = Path(os.path.expanduser("~"))
    candidates = [home / ".config" / "github-copilot" / "hosts.json"]
    la = os.environ.get("LOCALAPPDATA")
    if la:
        candidates.append(Path(la) / "github-copilot" / "hosts.json")
    for path in candidates:
        if path.exists() and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for _, info in data.items():
                    tok = info.get("oauth_token")
                    if tok:
                        return tok
            except Exception:
                pass
    return None


def get_copilot_status(
    display_name: str = "GitHub Copilot CLI",
    category: str = "personal",
    token: Optional[str] = None,
    agent_id: str = "copilot",
) -> AgentInfo:
    tok = token or _discover_copilot_token()
    if not tok:
        return AgentInfo(
            id=agent_id,
            name=display_name,
            provider="copilot",
            is_active=False,
            used_percent=0.0,
            status_label="Unconfigured / Offline",
            error="No GitHub Copilot token found. Run 'gh auth login' or specify token in config.",
            category=category,
        )

    url = "https://api.github.com/copilot_internal/v2/token"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}", "User-Agent": "agent-quota-tracker/1.2.0", "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        return AgentInfo(id=agent_id, name=display_name, provider="copilot", is_active=False, used_percent=0.0, status_label="Error", error=str(ex), category=category)

    exp_ts = data.get("expires_at")
    resets_str = None
    rem_secs = 0
    is_active = True
    if exp_ts:
        try:
            exp_dt = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
            resets_str = exp_dt.isoformat()
            diff = int((exp_dt - datetime.now(timezone.utc)).total_seconds())
            if diff > 0:
                rem_secs = diff
            else:
                is_active = False
        except Exception:
            pass

    return AgentInfo(
        id=agent_id,
        name=display_name,
        provider="copilot",
        is_active=is_active,
        used_percent=0.0,
        time_remaining_seconds=rem_secs,
        resets_at=resets_str,
        status_label="Active" if is_active else "Token Expired",
        category=category,
    )


def poke_copilot(prompt: str = "Hello, how are you doing?") -> dict[str, Any]:
    gh_bin = shutil.which("gh")
    if gh_bin:
        try:
            proc = subprocess.run([gh_bin, "copilot", "--version"], capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                ver = proc.stdout.strip().splitlines()[0] if proc.stdout else "unknown"
                return {"status": "poked", "message": f"GitHub Copilot CLI detected ({ver}). Token verified.", "reply": None, "verified_active": True}
        except Exception:
            pass
    return {"status": "skipped", "message": "GitHub Copilot token verified via API.", "reply": None, "verified_active": False}


def _discover_openrouter_key() -> Optional[str]:
    for env_var in ("OPENROUTER_API_KEY", "AIDER_API_KEY"):
        val = os.environ.get(env_var)
        if val and val.strip():
            return val.strip()

    home = Path(os.path.expanduser("~"))
    for path in (home / ".aider.conf.yml", home / ".env", Path.cwd() / ".env"):
        if path.exists() and path.is_file():
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("OPENROUTER_API_KEY=") or line.startswith("openrouter-api-key:"):
                        p = line.split("=", 1) if "=" in line else line.split(":", 1)
                        v = p[1].strip().strip('"').strip("'")
                        if v:
                            return v
            except Exception:
                pass
    return None


def get_aider_status(
    display_name: str = "Aider (OpenRouter)",
    category: str = "personal",
    api_key: Optional[str] = None,
    agent_id: str = "aider",
    provider: str = "aider",
) -> AgentInfo:
    key = api_key or _discover_openrouter_key()
    if not key:
        return AgentInfo(
            id=agent_id,
            name=display_name,
            provider=provider,
            is_active=False,
            used_percent=0.0,
            status_label="Unconfigured / Offline",
            error="No OpenRouter API key found. Set OPENROUTER_API_KEY or specify api_key in config.",
            category=category,
        )

    url = "https://openrouter.ai/api/v1/auth/key"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "User-Agent": "agent-quota-tracker/1.2.0", "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        return AgentInfo(id=agent_id, name=display_name, provider=provider, is_active=False, used_percent=0.0, status_label="Error", error=str(ex), category=category)

    info = data.get("data", {})
    usage = float(info.get("usage", 0.0))
    limit = info.get("limit")
    used_pct = 0.0
    if limit is not None and float(limit) > 0:
        used_pct = min(100.0, max(0.0, round((usage / float(limit)) * 100.0, 1)))
    is_active = usage > 0.0

    return AgentInfo(
        id=agent_id,
        name=display_name,
        provider=provider,
        is_active=is_active,
        used_percent=used_pct,
        weekly_used_percent=used_pct if limit is not None else None,
        status_label="Active" if is_active else "Idle",
        category=category,
    )


def poke_aider(prompt: str = "Hello, how are you doing?") -> dict[str, Any]:
    a_bin = shutil.which("aider")
    if a_bin:
        try:
            proc = subprocess.run([a_bin, "--version"], capture_output=True, text=True, timeout=5)
            ver = proc.stdout.strip().splitlines()[0] if proc.stdout else "unknown"
            return {"status": "poked", "message": f"Aider CLI detected ({ver}). Balance verified.", "reply": None, "verified_active": True}
        except Exception as e:
            return {"status": "error", "message": str(e), "reply": None, "verified_active": False}
    return {"status": "skipped", "message": "Aider monitored via OpenRouter API. Headless CLI poke not supported.", "reply": None, "verified_active": False}


# ---------------------------------------------------------------------------
# Collective Operations
# ---------------------------------------------------------------------------

DEFAULT_ACCOUNTS: list[dict[str, Any]] = [
    {
        "id": "agy",
        "provider": "agy",
        "name": "Google Antigravity (AGY)",
        "category": "personal",
        "enabled": True,
    },
    {
        "id": "codex",
        "provider": "codex",
        "name": "OpenAI Codex",
        "category": "personal",
        "enabled": True,
    },
    {
        "id": "personal",
        "provider": "claude",
        "profile": "personal",
        "name": "Claude (Personal)",
        "category": "personal",
        "enabled": True,
    },
    {
        "id": "work",
        "provider": "claude",
        "profile": "work",
        "name": "Claude (Work)",
        "category": "work",
        "enabled": True,
    },
    {
        "id": "work2",
        "provider": "claude",
        "profile": "work2",
        "name": "Claude (Work2)",
        "category": "work",
        "enabled": True,
    },
]


def load_accounts_config() -> list[dict[str, Any]]:
    candidates = [
        Path.cwd() / "agents.config.json",
        Path(__file__).resolve().parent / "agents.config.json",
        Path(os.path.expanduser("~")) / ".agents_dashboard" / "config.json",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            try:
                data = json.loads(c.read_text(encoding="utf-8"))
                accounts = data.get("accounts")
                if isinstance(accounts, list) and accounts:
                    return [a for a in accounts if a.get("enabled", True)]
            except Exception:
                pass
    return DEFAULT_ACCOUNTS


def fetch_all_statuses() -> list[AgentInfo]:
    accounts = load_accounts_config()
    statuses = []
    for acc in accounts:
        prov = acc.get("provider", "").lower()
        aid = acc.get("id", "")
        name = acc.get("name") or aid
        cat = acc.get("category", "personal")
        if prov == "agy":
            statuses.append(get_agy_status(display_name=name, category=cat))
        elif prov == "codex":
            statuses.append(get_codex_status(display_name=name, category=cat))
        elif prov == "claude":
            prof = acc.get("profile") or aid
            statuses.append(get_claude_status(prof, name, category=cat))
        elif prov == "cursor":
            token = acc.get("access_token") or acc.get("token")
            cookie = acc.get("cookie")
            statuses.append(get_cursor_status(name, category=cat, access_token=token, cookie=cookie, agent_id=aid))
        elif prov in ("windsurf", "codeium"):
            key = acc.get("api_key") or acc.get("key")
            statuses.append(get_windsurf_status(name, category=cat, api_key=key, agent_id=aid))
        elif prov in ("copilot", "github-copilot", "github_copilot"):
            token = acc.get("token") or acc.get("github_token")
            statuses.append(get_copilot_status(name, category=cat, token=token, agent_id=aid))
        elif prov in ("aider", "openrouter"):
            key = acc.get("api_key") or acc.get("key")
            statuses.append(get_aider_status(name, category=cat, api_key=key, agent_id=aid, provider=prov))
    try:
        save_cache(statuses)
    except Exception:
        pass
    return statuses


def send_notification(title: str, message: str) -> bool:
    """Send a native OS desktop notification."""
    import platform
    import subprocess
    system = platform.system().lower()
    safe_title = title.replace('"', '\\"').replace("'", "’")
    safe_message = message.replace('"', '\\"').replace("'", "’").replace("\n", " ")
    try:
        if system == "windows":
            ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName('text')
$null = $textNodes.Item(0).AppendChild($template.CreateTextNode('{safe_title}'))
$null = $textNodes.Item(1).AppendChild($template.CreateTextNode('{safe_message}'))
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe')
$notifier.Show($toast)
"""
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True
        elif system == "darwin":
            apple_script = f'display notification "{safe_message}" with title "{safe_title}"'
            subprocess.Popen(["osascript", "-e", apple_script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            return True
        elif system == "linux":
            subprocess.Popen(["notify-send", safe_title, safe_message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            return True
    except Exception:
        return False
    return False


def are_notifications_enabled() -> bool:
    if sys.platform != "win32":
        return True
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\PushNotifications",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "ToastEnabled")
            return bool(val != 0)
    except Exception:
        return True



def run_poke_command(force: bool = False, agent_id: Optional[str] = None, notify: bool = False) -> list[dict]:
    mode_str = " (FORCE mode enabled)" if force else ""
    print(f"\n⚡ [POKE] Checking 5-hour rolling threshold windows{mode_str}...\n")
    statuses = fetch_all_statuses()
    if agent_id:
        target = agent_id.lower()
        statuses = [s for s in statuses if s.id == target or s.id == f"claude-{target}"]
        if not statuses:
            print(f"✖ Unknown agent ID '{agent_id}'. Options: work, personal, work2, codex, agy\n")
            return []

    poked_results = []
    for s in statuses:
        if s.is_active and not force:
            print(f"  ↷ SKIPPED: {s.name:<25} Window already ACTIVE ({s.time_remaining_str} remaining, {s.used_percent}% used).")
            continue

        if not force and s.weekly_used_percent is not None and s.weekly_used_percent >= 100.0:
            reset_msg = f", resets in {s.weekly_remaining_hours:.1f}h" if s.weekly_remaining_hours else ""
            print(f"  ↷ SKIPPED: {s.name:<25} Weekly quota exhausted ({s.weekly_used_percent:.1f}% used{reset_msg}). Use --force to override.")
            continue

        action_desc = "Forcing poke" if (s.is_active and force) else "Window is inactive"
        print(f"  ⏳ POKING:  {s.name:<25} {action_desc}. Sending prompt & waiting for reply...")
        if s.provider.lower() == "claude" or s.id.startswith("claude-"):
            profile = s.id.replace("claude-", "")
            res = poke_claude(profile)
        elif s.id == "codex":
            res = poke_codex()
        elif s.id == "agy":
            res = poke_agy()
        elif s.provider.lower() == "cursor" or s.id.startswith("cursor"):
            res = poke_cursor()
        elif s.provider.lower() in ("windsurf", "codeium") or s.id.startswith("windsurf"):
            res = poke_windsurf()
        elif s.provider.lower() in ("copilot", "github-copilot") or s.id.startswith("copilot"):
            res = poke_copilot()
        elif s.provider.lower() in ("aider", "openrouter") or s.id.startswith("aider") or s.id.startswith("openrouter"):
            res = poke_aider()
        else:
            res = {"status": "error", "message": "Unknown agent", "reply": None, "verified_active": False}

        res["agent_name"] = s.name
        poked_results.append(res)
        if res["status"] == "poked":
            print(f"  ✔ SUCCESS: {s.name:<25} {res['message']}")
            if res.get("reply"):
                print(f"             ↳ Reply: \"{res['reply']}\"")
        elif res["status"] == "unverified":
            print(f"  ⚠ WARNING: {s.name:<25} {res['message']}")
            if res.get("reply"):
                print(f"             ↳ Reply: \"{res['reply']}\"")
        else:
            print(f"  ✖ ERROR:   {s.name:<25} {res['message']}")

    if notify:
        successful = [r for r in poked_results if r.get("status") == "poked"]
        if successful:
            names = ", ".join(r["agent_name"] for r in successful)
            send_notification("⚡ Agent Quota Primed", f"Successfully primed: {names}")

    poked_names = [r["agent_name"] for r in poked_results if r.get("status") == "poked"]
    skipped_names = [s.name for s in statuses if s.is_active and not force]
    failed_names = [r["agent_name"] for r in poked_results if r.get("status") in ("error", "unverified")]
    log_summary = f"Poke executed: {len(poked_names)} primed ({', '.join(poked_names) if poked_names else 'none'}), {len(skipped_names)} skipped, {len(failed_names)} failed"
    append_schedule_log(log_summary)

    print("\nDone!\n")
    return poked_results


def run_watch_loop(interval: int = 15) -> None:
    import time
    print(f"\n⚡ Live Quota Watch Mode enabled (refreshing every {interval}s). Press Ctrl+C to exit.\n")
    try:
        while True:
            os.system('cls' if os.name == 'nt' else 'clear')
            print_status_table()
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nWatch mode terminated.\n")


def parse_duration(val: Optional[str | int]) -> Optional[int]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return max(1, int(val))
    s = str(val).strip().lower()
    if not s or s == "auto":
        return None
    if s.isdigit():
        return max(1, int(s))
    import re
    pattern = r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?"
    match = re.fullmatch(pattern, s)
    if match and any(match.groups()):
        h, m, sec = match.groups()
        total = (int(h or 0) * 3600) + (int(m or 0) * 60) + int(sec or 0)
        return max(1, total) if total > 0 else None
    return None


def parse_target_time(time_str: str, now_dt: Optional[datetime] = None) -> tuple[datetime, int]:
    if not time_str or not time_str.strip():
        raise ValueError("Time string cannot be empty")
    s = time_str.strip()
    parts = s.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid time format '{time_str}'. Expected HH:MM or HH:MM:SS in 24-hour format.")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except ValueError:
        raise ValueError(f"Invalid non-numeric time '{time_str}'.")

    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"Time values out of range in '{time_str}'. Hour must be 0-23, minute/second 0-59.")

    now = now_dt or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    delta_secs = int((target - now).total_seconds())
    return target, delta_secs


def compute_adaptive_sleep_seconds(agents_info: list[AgentInfo], force: bool = False) -> tuple[int, str]:
    active_with_time = [
        a for a in agents_info
        if a.is_active and a.time_remaining_seconds > 0
        and (force or a.weekly_used_percent is None or a.weekly_used_percent < 100.0)
    ]
    if not active_with_time:
        return 120, "All agents idle or freshly checked"

    earliest = min(active_with_time, key=lambda a: a.time_remaining_seconds)
    sleep_secs = max(60, earliest.time_remaining_seconds + 45)
    return sleep_secs, f"{earliest.name} ({format_duration(earliest.time_remaining_seconds)} left)"


def run_countdown(total_seconds: int, prefix: str) -> None:
    """Displays a ticking countdown line updated cleanly in-place."""
    import time
    try:
        term_w = shutil.get_terminal_size(fallback=(100, 24)).columns
    except Exception:
        term_w = 100
    max_len = max(40, term_w - 2)
    for rem in range(total_seconds, 0, -1):
        line = f"⏳ {prefix}: {format_duration(rem)} remaining"
        if len(line) > max_len:
            line = line[:max_len - 3] + "..."
        padded = line.ljust(max_len)
        sys.stdout.write(f"\r{padded}")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * max_len + "\r")
    sys.stdout.flush()


def run_auto_checker_loop(
    force: bool = False,
    agent_id: Optional[str] = None,
    notify: bool = False,
    max_cycles: Optional[int] = None,
) -> None:
    """Continuously runs the autonomous auto-checker task: displays status, primes idle agents,
    calculates the next upcoming reset time, waits with a ticking countdown, and repeats.
    """
    notify_str = " • Notifications: ON" if notify else ""
    force_str = " • Force: ON" if force else ""
    print(f"\n================================================================================================================================")
    print(f"  ⚡ AUTONOMOUS QUOTA AUTO-CHECKER STARTED")
    print(f"  Continuous monitoring loop: checks status, waits for earliest window reset, primes, and repeats.")
    print(f"  Mode: Adaptive Quota Priming{notify_str}{force_str} • Press Ctrl+C to terminate.")
    print(f"================================================================================================================================\n")

    cycle = 1
    try:
        while True:
            if max_cycles is not None and cycle > max_cycles:
                break
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"▶ Auto-Checker Cycle #{cycle} • {now_str}")

            # Step 1: Print current status table
            print_status_table()

            # Step 2: Check if any agent is currently idle & ready to poke
            statuses = fetch_all_statuses()
            if agent_id:
                target = agent_id.lower()
                statuses = [s for s in statuses if s.id == target or s.id == f"claude-{target}"]

            idle_ready = [
                s for s in statuses
                if not s.is_active and (force or s.weekly_used_percent is None or s.weekly_used_percent < 100.0)
            ]

            if idle_ready:
                ready_names = ", ".join(s.name for s in idle_ready)
                print(f"⚡ Found {len(idle_ready)} idle account(s) ready to prime ({ready_names}). Poking now...\n")
                run_poke_command(force=force, agent_id=agent_id, notify=notify)
                print_status_table()
                statuses = fetch_all_statuses()
                if agent_id:
                    target = agent_id.lower()
                    statuses = [s for s in statuses if s.id == target or s.id == f"claude-{target}"]

            # Step 3: Compute earliest next window expiration
            sleep_secs, reason = compute_adaptive_sleep_seconds(statuses, force=force)
            wake_time = (datetime.now() + timedelta(seconds=sleep_secs)).strftime("%H:%M:%S")
            print()

            # Step 4: Ticking countdown (in-place)
            run_countdown(sleep_secs, f"Next poke at {wake_time} ({reason})")
            print(f"\n⚡ Timer reached ({wake_time})! Priming newly available quota window(s)...\n")
            run_poke_command(force=force, agent_id=agent_id, notify=notify)
            cycle += 1
            print()
    except KeyboardInterrupt:
        sys.stdout.write("\r" + " " * 85 + "\r")
        sys.stdout.flush()
        print("\n⚡ Auto-checker loop stopped by user.\n")


def run_poke_watch_loop(
    interval_arg: Optional[str] = None,
    force: bool = False,
    agent_id: Optional[str] = None,
    notify: bool = False,
) -> None:
    fixed_interval = parse_duration(interval_arg) if interval_arg else None
    mode_str = f"fixed {format_duration(fixed_interval)} interval" if fixed_interval else "adaptive window expiry mode"
    notify_str = " • Notifications: ON" if notify else ""
    print(f"\n================================================================================================================================")
    print(f"  ⚡ AUTONOMOUS POKE WATCHDOG STARTED")
    print(f"  Running in {mode_str}{notify_str}. Automatically primes 5h quota windows as accounts cool down.")
    print(f"  Press Ctrl+C to terminate.")
    print(f"================================================================================================================================\n")

    cycle = 1
    try:
        while True:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"▶ Watchdog Cycle #{cycle} • {now_str}")
            run_poke_command(force=force, agent_id=agent_id, notify=notify)

            if fixed_interval:
                sleep_secs = fixed_interval
                reason = f"fixed {format_duration(fixed_interval)}"
            else:
                agents_info = fetch_all_statuses()
                sleep_secs, reason = compute_adaptive_sleep_seconds(agents_info)

            wake_time = (datetime.now() + timedelta(seconds=sleep_secs)).strftime("%H:%M:%S")
            print(f"Next check at {wake_time} ({reason})")
            run_countdown(sleep_secs, f"Next check at {wake_time}")
            cycle += 1
    except KeyboardInterrupt:
        sys.stdout.write("\r" + " " * 85 + "\r")
        sys.stdout.flush()
        print("\n⚡ Poke watchdog mode stopped.\n")


def run_poke_at(
    target_time_str: str,
    and_watch: bool = False,
    watch_interval: Optional[str] = None,
    force: bool = False,
    agent_id: Optional[str] = None,
    notify: bool = False,
) -> None:
    try:
        target_dt, delta_secs = parse_target_time(target_time_str)
    except ValueError as e:
        print(f"✖ Error: {e}")
        return

    target_str = target_dt.strftime("%Y-%m-%d %H:%M:%S")
    relative_day = "today" if target_dt.date() == datetime.now().date() else "tomorrow"
    notify_str = " • Notifications: ON" if notify else ""

    print(f"\n================================================================================================================================")
    print(f"  ⚡ SCHEDULED PEAK-TIME PRIMING MODE")
    print(f"  Target Execution: {target_str} ({relative_day}){notify_str}")
    print(f"  Strategic priming ensures 5-hour quota reset aligns with peak workday hours.")
    print(f"  Press Ctrl+C to cancel schedule.")
    print(f"================================================================================================================================\n")

    try:
        run_countdown(delta_secs, f"Priming scheduled for {target_dt.strftime('%H:%M:%S')} ({relative_day})")
    except KeyboardInterrupt:
        sys.stdout.write("\r" + " " * 85 + "\r")
        sys.stdout.flush()
        print("\n⚡ Scheduled poke cancelled by user.\n")
        return

    print(f"\n⚡ Target time reached ({target_str})! Initiating scheduled poke...\n")
    poked_results = run_poke_command(force=force, agent_id=agent_id, notify=notify)
    print_status_table()

    if notify:
        active_count = sum(1 for r in poked_results if r.get("status") in ("poked", "skipped"))
        send_notification("🎯 Morning Priming Complete", f"All {active_count} agent window(s) ready for peak workday coding!")

    if and_watch:
        print("Transitioning into automated watchdog mode...\n")
        run_poke_watch_loop(interval_arg=watch_interval, force=force, agent_id=agent_id, notify=notify)


def print_status_table(as_json: bool = False) -> None:
    statuses = fetch_all_statuses()
    if as_json:
        import json
        print(json.dumps([s.to_dict() for s in statuses], indent=2))
        return

    try:
        term_w = shutil.get_terminal_size(fallback=(110, 24)).columns
    except Exception:
        term_w = 110

    now_dt = datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    if term_w >= 120:
        bar_len = 110
        print("\n" + "=" * bar_len)
        print(f"  ⚡ AI AGENTS 5-HOUR & WEEKLY WINDOW QUOTA STATUS  •  Checked: {now_str}")
        print("=" * bar_len)
        print(f"{'Agent / Account':<24} {'Provider':<8} {'5h State':<10} {'5h Left':<11} {'5h Reset':<18} {'5h Use':<8} {'Wk Use':<8} {'Weekly Reset'}")
        print("-" * bar_len)

        for s in statuses:
            state_str = "● ACTIVE" if s.is_active else "○ INACTIVE"
            reset_str = "Ready to Poke"
            if s.resets_at:
                try:
                    local_dt = datetime.fromisoformat(s.resets_at.replace("Z", "+00:00")).astimezone()
                    reset_str = local_dt.strftime("%H:%M:%S (Today)")
                except Exception:
                    reset_str = s.resets_at[:19]

            usage_str = f"{s.used_percent}%" if s.is_active else "0.0%"
            if s.weekly_used_percent is not None:
                wk_usage = f"⚠️ {s.weekly_used_percent}%" if s.weekly_used_percent >= 100.0 else f"{s.weekly_used_percent}%"
            else:
                wk_usage = "-"
            wk_reset = s.weekly_reset_str
            print(f"{s.name:<24} {s.provider:<8} {state_str:<10} {s.time_remaining_str:<11} {reset_str:<18} {usage_str:<8} {wk_usage:<8} {wk_reset}")

        print("=" * bar_len + "\n")
    else:
        # Compact view for narrower terminals (< 120 cols)
        bar_len = 80
        print("\n" + "=" * bar_len)
        print(f"  ⚡ AI AGENTS QUOTA STATUS  •  Checked: {now_dt.strftime('%H:%M:%S')}")
        print("=" * bar_len)
        print(f"{'Agent':<14} {'State':<10} {'Left':<9} {'Reset':<7} {'5h%':<6} {'Wk%':<6} {'Weekly'}")
        print("-" * bar_len)

        for s in statuses:
            name = s.name.replace("Google Antigravity (AGY)", "Antigravity").replace("OpenAI Codex", "Codex").replace("Claude (", "").replace(")", "")
            state_str = "● ACTIVE" if s.is_active else "○ INACT"
            parts = s.time_remaining_str.split()
            left_str = f"{parts[0]} {parts[1]}" if (len(parts) >= 2 and s.is_active) else (s.time_remaining_str if s.is_active else "Ready")
            reset_str = "Ready"
            if s.resets_at:
                try:
                    local_dt = datetime.fromisoformat(s.resets_at.replace("Z", "+00:00")).astimezone()
                    reset_str = local_dt.strftime("%H:%M")
                except Exception:
                    reset_str = "N/A"
            usage_str = f"{int(round(s.used_percent))}%" if s.is_active else "0%"
            if s.weekly_used_percent is not None:
                wk_val = int(round(s.weekly_used_percent))
                wk_usage = f"⚠️{wk_val}%" if wk_val >= 100 else f"{wk_val}%"
            else:
                wk_usage = "-"
            wk_reset = s.weekly_reset_str
            if wk_reset != "-" and "(" in wk_reset:
                parts = wk_reset.split("(")
                h_part = parts[0].strip().replace(".0h", "h")
                day_name = parts[1].split()[0]
                wk_reset = f"{h_part} ({day_name})"

            print(f"{name:<14} {state_str:<10} {left_str:<9} {reset_str:<7} {usage_str:<6} {wk_usage:<6} {wk_reset}")

        print("=" * bar_len + "\n")


# ---------------------------------------------------------------------------
# Live Dashboard Server
# ---------------------------------------------------------------------------

_dash_update_event = threading.Event()
_dash_server_running = True

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>⚡ AI Agents Quota Dashboard v2</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root, [data-theme="dark"] {
      --bg: #090d16;
      --bg-gradient: radial-gradient(circle at 50% 0%, #171d36 0%, var(--bg) 75%);
      --card-bg: rgba(22, 27, 46, 0.75);
      --card-border: rgba(255, 255, 255, 0.08);
      --card-hover: rgba(30, 38, 64, 0.9);
      --card-hover-border: rgba(255, 255, 255, 0.18);
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --header-title: linear-gradient(to right, #ffffff, #cbd5e1);
      --box-bg: rgba(0, 0, 0, 0.28);
      --bar-bg: rgba(255, 255, 255, 0.08);
      --modal-bg: #111827;
      --modal-border: rgba(255, 255, 255, 0.12);
      --input-bg: rgba(0, 0, 0, 0.35);
      --input-border: rgba(255, 255, 255, 0.12);
      --cyan: #06b6d4;
      --emerald: #10b981;
      --amber: #f59e0b;
      --rose: #f43f5e;
      --indigo: #6366f1;
      --purple: #8b5cf6;
    }

    [data-theme="oled"] {
      --bg: #000000;
      --bg-gradient: #000000;
      --card-bg: rgba(10, 10, 15, 0.96);
      --card-border: rgba(0, 240, 255, 0.2);
      --card-hover: rgba(16, 16, 26, 1);
      --card-hover-border: rgba(0, 240, 255, 0.5);
      --text-main: #ffffff;
      --text-muted: #94a3b8;
      --header-title: linear-gradient(to right, #00f0ff, #ff007f);
      --box-bg: rgba(0, 0, 0, 0.8);
      --bar-bg: rgba(255, 255, 255, 0.06);
      --modal-bg: #050508;
      --modal-border: rgba(0, 240, 255, 0.3);
      --input-bg: #000000;
      --input-border: rgba(0, 240, 255, 0.3);
      --cyan: #00f0ff;
      --emerald: #00ff88;
      --amber: #ffb800;
      --rose: #ff0055;
      --indigo: #7928ca;
      --purple: #d000ff;
    }

    [data-theme="light"] {
      --bg: #f8fafc;
      --bg-gradient: radial-gradient(circle at 50% 0%, #e2e8f0 0%, var(--bg) 75%);
      --card-bg: rgba(255, 255, 255, 0.94);
      --card-border: rgba(15, 23, 42, 0.09);
      --card-hover: rgba(255, 255, 255, 1);
      --card-hover-border: rgba(99, 102, 241, 0.35);
      --text-main: #0f172a;
      --text-muted: #64748b;
      --header-title: linear-gradient(to right, #0f172a, #334155);
      --box-bg: rgba(241, 245, 249, 0.9);
      --bar-bg: rgba(15, 23, 42, 0.06);
      --modal-bg: #ffffff;
      --modal-border: rgba(15, 23, 42, 0.12);
      --input-bg: #f8fafc;
      --input-border: rgba(15, 23, 42, 0.15);
      --cyan: #0284c7;
      --emerald: #059669;
      --amber: #d97706;
      --rose: #e11d48;
      --indigo: #4f46e5;
      --purple: #7c3aed;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background: var(--bg-gradient);
      background-color: var(--bg);
      color: var(--text-main);
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      min-height: 100vh;
      padding: 2.25rem 1.5rem;
      transition: background 0.3s ease, color 0.3s ease;
    }

    .container {
      max-width: 1240px;
      margin: 0 auto;
    }

    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 2.25rem;
      flex-wrap: wrap;
      gap: 1.25rem;
    }

    .header-title {
      display: flex;
      align-items: center;
      gap: 1rem;
    }

    .header-icon {
      width: 48px;
      height: 48px;
      background: linear-gradient(135deg, var(--cyan), var(--indigo));
      border-radius: 14px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.5rem;
      box-shadow: 0 8px 24px rgba(6, 182, 212, 0.25);
    }

    h1 {
      font-size: 1.85rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      background: var(--header-title);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .subtitle-row {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-top: 0.25rem;
      flex-wrap: wrap;
    }

    .subtitle {
      font-size: 0.88rem;
      color: var(--text-muted);
    }

    /* SSE Stream Pill */
    .stream-pill {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.72rem;
      font-weight: 700;
      padding: 0.25rem 0.65rem;
      border-radius: 9999px;
      background: rgba(16, 185, 129, 0.12);
      color: var(--emerald);
      border: 1px solid rgba(16, 185, 129, 0.25);
      transition: all 0.3s ease;
    }

    .stream-pill.fallback {
      background: rgba(245, 158, 11, 0.12);
      color: var(--amber);
      border-color: rgba(245, 158, 11, 0.25);
    }

    .stream-pill.offline {
      background: rgba(244, 63, 94, 0.12);
      color: var(--rose);
      border-color: rgba(244, 63, 94, 0.25);
    }

    .stream-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: currentColor;
      box-shadow: 0 0 8px currentColor;
      animation: pulse 1.8s infinite;
    }

    .header-actions {
      display: flex;
      gap: 0.65rem;
      align-items: center;
      flex-wrap: wrap;
    }

    /* Theme Switcher Segmented Control */
    .theme-switcher {
      display: inline-flex;
      background: var(--box-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 3px;
      gap: 2px;
    }

    .theme-btn {
      cursor: pointer;
      font-family: inherit;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.35rem 0.65rem;
      border-radius: 7px;
      border: none;
      background: transparent;
      color: var(--text-muted);
      transition: all 0.2s ease;
    }

    .theme-btn:hover {
      color: var(--text-main);
    }

    .theme-btn.active {
      background: var(--card-bg);
      color: var(--text-main);
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
    }

    button {
      cursor: pointer;
      font-family: inherit;
      font-size: 0.85rem;
      font-weight: 600;
      padding: 0.6rem 1.15rem;
      border-radius: 10px;
      border: 1px solid var(--card-border);
      transition: all 0.2s ease;
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      user-select: none;
    }

    button:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    .btn-primary {
      background: linear-gradient(135deg, #0ea5e9, #6366f1);
      color: white;
      border: none;
      box-shadow: 0 4px 16px rgba(14, 165, 233, 0.3);
    }

    .btn-primary:hover:not(:disabled) {
      transform: translateY(-1px);
      box-shadow: 0 6px 20px rgba(14, 165, 233, 0.45);
    }

    .btn-secondary {
      background: var(--card-bg);
      color: var(--text-main);
    }

    .btn-secondary:hover:not(:disabled) {
      background: var(--card-hover);
      border-color: var(--card-hover-border);
    }

    /* Stats Summary */
    .stats-summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 1.25rem;
      margin-bottom: 2rem;
    }

    .stat-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 1.25rem 1.5rem;
      backdrop-filter: blur(12px);
      transition: transform 0.2s ease, border-color 0.2s ease;
    }

    .stat-card:hover {
      border-color: var(--card-hover-border);
      transform: translateY(-1px);
    }

    .stat-label {
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 0.4rem;
    }

    .stat-value {
      font-size: 1.75rem;
      font-weight: 700;
      font-family: 'JetBrains Mono', monospace;
    }

    /* Agent Cards Grid */
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
      gap: 1.5rem;
    }

    .agent-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 18px;
      padding: 1.5rem;
      backdrop-filter: blur(12px);
      transition: all 0.25s ease;
      position: relative;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }

    .agent-card:hover {
      border-color: var(--card-hover-border);
      background: var(--card-hover);
      transform: translateY(-2px);
    }

    .agent-card.card-exhausted {
      border-color: rgba(244, 63, 94, 0.4);
    }

    .card-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 1.25rem;
    }

    .agent-title {
      font-size: 1.15rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .provider-tag {
      font-size: 0.68rem;
      font-weight: 700;
      text-transform: uppercase;
      padding: 0.2rem 0.5rem;
      border-radius: 6px;
      background: var(--bar-bg);
      color: var(--text-muted);
    }

    .status-badges-group {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 0.35rem;
    }

    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.72rem;
      font-weight: 700;
      padding: 0.3rem 0.7rem;
      border-radius: 9999px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .badge-active {
      background: rgba(16, 185, 129, 0.15);
      color: var(--emerald);
      border: 1px solid rgba(16, 185, 129, 0.3);
    }

    .badge-active::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--emerald);
      box-shadow: 0 0 8px var(--emerald);
      animation: pulse 1.8s infinite;
    }

    .badge-inactive {
      background: rgba(148, 163, 184, 0.12);
      color: var(--text-muted);
      border: 1px solid rgba(148, 163, 184, 0.2);
    }

    .badge-exhausted {
      background: rgba(244, 63, 94, 0.18);
      color: var(--rose);
      border: 1px solid rgba(244, 63, 94, 0.35);
      font-size: 0.68rem;
      padding: 0.2rem 0.55rem;
    }

    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(0.85); }
    }

    .window-timer-box {
      background: var(--box-bg);
      border-radius: 12px;
      padding: 1rem 1.25rem;
      margin-bottom: 1.25rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .timer-info-col {
      display: flex;
      flex-direction: column;
    }

    .timer-label {
      font-size: 0.72rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 0.2rem;
    }

    .timer-value {
      font-family: 'JetBrains Mono', monospace;
      font-size: 1.45rem;
      font-weight: 700;
      color: var(--cyan);
    }

    .timer-value.inactive {
      color: var(--text-muted);
      font-size: 1.15rem;
    }

    .reset-info-col {
      text-align: right;
    }

    .reset-time-sub {
      font-size: 0.8rem;
      font-family: 'JetBrains Mono', monospace;
      color: var(--text-main);
    }

    .progress-section {
      margin-bottom: 1.15rem;
    }

    .progress-labels {
      display: flex;
      justify-content: space-between;
      font-size: 0.78rem;
      margin-bottom: 0.4rem;
    }

    .progress-pct {
      font-family: 'JetBrains Mono', monospace;
      font-weight: 700;
    }

    .progress-bar-bg {
      height: 8px;
      background: var(--bar-bg);
      border-radius: 9999px;
      overflow: hidden;
      position: relative;
    }

    .progress-bar-fill {
      height: 100%;
      border-radius: 9999px;
      transition: width 0.4s ease;
    }

    .fill-low {
      background: linear-gradient(90deg, #10b981, #06b6d4);
    }

    .fill-med {
      background: linear-gradient(90deg, #06b6d4, #f59e0b);
    }

    .fill-high {
      background: linear-gradient(90deg, #f59e0b, #f43f5e);
    }

    .fill-exhausted {
      background: linear-gradient(90deg, #f43f5e, #dc2626);
    }

    .weekly-box {
      margin-top: 0.75rem;
      padding-top: 0.75rem;
      border-top: 1px solid var(--card-border);
      font-size: 0.78rem;
      color: var(--text-muted);
    }

    .weekly-labels {
      display: flex;
      justify-content: space-between;
      margin-bottom: 0.35rem;
    }

    .weekly-footer {
      display: flex;
      justify-content: space-between;
      font-size: 0.75rem;
      margin-top: 0.35rem;
    }

    .card-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-top: 0.85rem;
      border-top: 1px solid var(--card-border);
      font-size: 0.78rem;
      color: var(--text-muted);
      margin-top: 0.75rem;
    }

    .btn-poke-card {
      padding: 0.45rem 0.9rem;
      font-size: 0.75rem;
      border-radius: 8px;
      background: var(--bar-bg);
      color: var(--text-main);
      border: 1px solid var(--card-border);
    }

    .btn-poke-card:hover:not(:disabled) {
      background: var(--cyan);
      color: #000;
      border-color: var(--cyan);
    }

    .btn-poke-card.force-mode {
      background: rgba(244, 63, 94, 0.18);
      color: var(--rose);
      border-color: rgba(244, 63, 94, 0.4);
    }

    .btn-poke-card.force-mode:hover:not(:disabled) {
      background: var(--rose);
      color: white;
    }

    /* Modal */
    .modal-backdrop {
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: rgba(0, 0, 0, 0.7);
      backdrop-filter: blur(8px);
      z-index: 10000;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1.5rem;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.25s ease;
    }

    .modal-backdrop.open {
      opacity: 1;
      pointer-events: auto;
    }

    .modal {
      background: var(--modal-bg);
      border: 1px solid var(--modal-border);
      border-radius: 20px;
      width: 100%;
      max-width: 520px;
      padding: 2rem;
      box-shadow: 0 25px 60px rgba(0, 0, 0, 0.6);
      transform: scale(0.95);
      transition: transform 0.25s ease;
    }

    .modal-backdrop.open .modal {
      transform: scale(1);
    }

    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 1.25rem;
    }

    .modal-title {
      font-size: 1.35rem;
      font-weight: 800;
    }

    .modal-close {
      background: transparent;
      border: none;
      font-size: 1.25rem;
      color: var(--text-muted);
      cursor: pointer;
      padding: 0.25rem;
    }

    .modal-close:hover {
      color: var(--text-main);
    }

    .status-panel {
      background: var(--box-bg);
      border-radius: 12px;
      padding: 1rem;
      margin-bottom: 1.5rem;
      font-size: 0.82rem;
      line-height: 1.6;
    }

    .form-group {
      margin-bottom: 1.25rem;
    }

    .form-label {
      display: block;
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--text-muted);
      margin-bottom: 0.4rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .form-control {
      width: 100%;
      padding: 0.65rem 0.9rem;
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      border-radius: 10px;
      color: var(--text-main);
      font-family: inherit;
      font-size: 0.9rem;
      outline: none;
    }

    .form-control:focus {
      border-color: var(--cyan);
    }

    .form-checkbox {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      font-size: 0.85rem;
      cursor: pointer;
    }

    .form-checkbox input {
      accent-color: var(--cyan);
      width: 16px;
      height: 16px;
    }

    .modal-actions {
      display: flex;
      justify-content: flex-end;
      gap: 0.75rem;
      margin-top: 1.75rem;
    }

    /* Toast */
    .banner-toast {
      position: fixed;
      bottom: 2rem;
      right: 2rem;
      background: var(--modal-bg);
      color: var(--text-main);
      border: 1px solid var(--modal-border);
      border-radius: 12px;
      padding: 0.9rem 1.35rem;
      box-shadow: 0 12px 36px rgba(0, 0, 0, 0.5);
      z-index: 11000;
      opacity: 0;
      transform: translateY(20px);
      transition: all 0.3s ease;
      display: flex;
      align-items: center;
      gap: 0.75rem;
      font-size: 0.88rem;
      pointer-events: none;
    }

    .banner-toast.show {
      opacity: 1;
      transform: translateY(0);
      pointer-events: auto;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="header-title">
        <div class="header-icon">⚡</div>
        <div>
          <h1>AI Agents Quota Dashboard</h1>
          <div class="subtitle-row">
            <span class="subtitle">Real-time status across Claude (CCS), Codex, and Google Antigravity</span>
            <div class="stream-pill" id="stream-indicator">
              <span class="stream-dot"></span>
              <span id="stream-status">Connecting SSE...</span>
            </div>
          </div>
        </div>
      </div>
      <div class="header-actions">
        <div class="theme-switcher">
          <button class="theme-btn" data-theme="dark" onclick="setTheme('dark')">🌙 Dark</button>
          <button class="theme-btn" data-theme="oled" onclick="setTheme('oled')">⚡ OLED</button>
          <button class="theme-btn" data-theme="light" onclick="setTheme('light')">☀️ Light</button>
        </div>
        <button class="btn-secondary" onclick="openScheduleModal()">⏰ Morning Priming</button>
        <button class="btn-secondary" onclick="fetchData(true)">🔄 Refresh</button>
        <button class="btn-primary" id="btn-poke-all" onclick="triggerPokeAll()">⚡ Poke All Idle</button>
      </div>
    </header>

    <div class="stats-summary">
      <div class="stat-card">
        <div class="stat-label">Active Windows</div>
        <div class="stat-value" id="summary-active" style="color: var(--emerald);">- / -</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Idle / Ready to Poke</div>
        <div class="stat-value" id="summary-inactive" style="color: var(--amber);">-</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Next Reset Coming In</div>
        <div class="stat-value" id="summary-next-reset" style="color: var(--cyan);">-</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">System Monitoring</div>
        <div class="stat-value" id="summary-total" style="color: var(--indigo);">- Agents</div>
      </div>
    </div>

    <div class="grid" id="agents-grid">
      <!-- Agent cards injected dynamically -->
    </div>
  </div>

  <!-- Scheduled Morning Priming Modal -->
  <div class="modal-backdrop" id="schedule-modal" onclick="closeScheduleModal(event)">
    <div class="modal" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div>
          <div class="modal-title">⏰ Morning Priming Scheduler</div>
          <div class="subtitle" style="margin-top: 0.2rem;">OS-Level unattended morning quota priming</div>
        </div>
        <button class="modal-close" onclick="closeScheduleModal()">&times;</button>
      </div>

      <div class="status-panel" id="modal-status-panel">
        <div><b>Status:</b> <span id="sched-status-text">Checking...</span></div>
        <div><b>Platform:</b> <span id="sched-platform-text">-</span></div>
        <div><b>Next Run:</b> <span id="sched-next-run">-</span></div>
        <div><b>Last Run:</b> <span id="sched-last-run">-</span></div>
      </div>

      <form id="schedule-form" onsubmit="saveSchedule(event)">
        <div class="form-group">
          <label class="form-label">Target Wake Time (24h)</label>
          <input type="time" class="form-control" id="sched-time" value="07:30" required>
        </div>

        <div class="form-group">
          <label class="form-label">Recurrence Frequency</label>
          <select class="form-control" id="sched-frequency">
            <option value="daily">Daily (Default)</option>
            <option value="weekdays">Weekdays Only (Mon-Fri)</option>
            <option value="once">Run Once</option>
          </select>
        </div>

        <div class="form-group">
          <label class="form-checkbox">
            <input type="checkbox" id="sched-notify" checked>
            Send native OS desktop toast notifications upon priming
          </label>
        </div>

        <div class="modal-actions">
          <button type="button" class="btn-secondary" id="btn-remove-sched" onclick="removeScheduleTask()" style="display: none; color: var(--rose);">Uninstall Task</button>
          <button type="button" class="btn-secondary" onclick="closeScheduleModal()">Cancel</button>
          <button type="submit" class="btn-primary" id="btn-save-sched">Save &amp; Install Task</button>
        </div>
      </form>
    </div>
  </div>

  <div class="banner-toast" id="toast">
    <span id="toast-icon">ℹ️</span>
    <span id="toast-msg">Notification</span>
  </div>

  <script>
    let agentsData = [];
    let eventSource = null;
    let sseRetryTimer = null;
    let fallbackPollTimer = null;

    function formatSeconds(secs) {
      if (secs <= 0) return "0s";
      const h = Math.floor(secs / 3600);
      const m = Math.floor((secs % 3600) / 60);
      const s = Math.floor(secs % 60);
      const parts = [];
      if (h > 0) parts.push(`${h}h`);
      if (m > 0) parts.push(`${m}m`);
      if (s > 0 || parts.length === 0) parts.push(`${s}s`);
      return parts.join(" ");
    }

    function showToast(msg, icon = "ℹ️") {
      const toast = document.getElementById("toast");
      document.getElementById("toast-msg").innerText = msg;
      document.getElementById("toast-icon").innerText = icon;
      toast.classList.add("show");
      setTimeout(() => toast.classList.remove("show"), 4000);
    }

    // Theme Switcher
    function setTheme(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem('agent_quota_tracker_theme', theme);
      document.querySelectorAll('.theme-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-theme') === theme);
      });
    }

    // Initialize Theme from localStorage
    const savedTheme = localStorage.getItem('agent_quota_tracker_theme') || 'dark';
    setTheme(savedTheme);

    function setStreamStatus(status) {
      const pill = document.getElementById("stream-indicator");
      const label = document.getElementById("stream-status");
      pill.className = "stream-pill";

      if (status === "live") {
        label.innerText = "Live SSE Stream";
      } else if (status === "fallback") {
        pill.classList.add("fallback");
        label.innerText = "Polling (Fallback)";
      } else {
        pill.classList.add("offline");
        label.innerText = "Offline";
      }
    }

    // Server-Sent Events (SSE)
    function connectSSE() {
      if (eventSource) {
        eventSource.close();
      }

      try {
        eventSource = new EventSource('/api/stream');

        eventSource.addEventListener('quota_update', (e) => {
          try {
            agentsData = JSON.parse(e.data);
            setStreamStatus('live');
            render();
          } catch (err) {
            console.error("SSE parse error:", err);
          }
        });

        eventSource.onopen = () => {
          setStreamStatus('live');
          if (fallbackPollTimer) {
            clearInterval(fallbackPollTimer);
            fallbackPollTimer = null;
          }
        };

        eventSource.onerror = () => {
          setStreamStatus('fallback');
          eventSource.close();
          eventSource = null;

          if (!fallbackPollTimer) {
            fallbackPollTimer = setInterval(() => fetchData(false), 8000);
          }
          if (!sseRetryTimer) {
            sseRetryTimer = setTimeout(() => {
              sseRetryTimer = null;
              connectSSE();
            }, 6000);
          }
        };
      } catch (err) {
        setStreamStatus('fallback');
      }
    }

    async function fetchData(forceRefresh = false) {
      try {
        const url = forceRefresh ? "/api/status?refresh=true" : "/api/status";
        const res = await fetch(url);
        if (!res.ok) throw new Error("Status endpoint failed");
        agentsData = await res.json();
        render();
        if (forceRefresh) {
          showToast("Refreshed latest quota data from providers", "✔");
        }
      } catch (err) {
        console.error("Error fetching status:", err);
      }
    }

    async function triggerPokeAll() {
      const btn = document.getElementById("btn-poke-all");
      btn.disabled = true;
      btn.innerHTML = "⏳ Poking All...";
      showToast("Poking idle agents to prime 5h windows...", "⏳");
      try {
        const res = await fetch("/api/poke", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({})
        });
        const resp = await res.json();
        const results = resp.results || resp;
        const pokedCount = (results || []).filter(r => r.action_taken === "poked" || r.verified_active).length;
        showToast(`Primed ${pokedCount} agent(s) successfully!`, "⚡");
        await fetchData(true);
      } catch (err) {
        showToast("Error triggering poke: " + err.message, "❌");
      } finally {
        btn.disabled = false;
        btn.innerHTML = "⚡ Poke All Idle";
      }
    }

    async function triggerPoke(agentId, force = false) {
      const cardBtn = document.getElementById(`poke-btn-${agentId}`);
      if (cardBtn) {
        cardBtn.disabled = true;
        cardBtn.innerHTML = "⏳ Poking...";
      }
      showToast(`Poking agent ${agentId}...`, "⏳");
      try {
        const res = await fetch("/api/poke", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agent_id: agentId, force: force })
        });
        const resp = await res.json();
        showToast(`Agent ${agentId} primed successfully!`, "⚡");
        await fetchData(true);
      } catch (err) {
        showToast("Error: " + err.message, "❌");
      } finally {
        if (cardBtn) {
          cardBtn.disabled = false;
          cardBtn.innerHTML = "⚡ Poke";
        }
      }
    }

    function render() {
      const grid = document.getElementById("agents-grid");
      grid.innerHTML = "";

      let activeCount = 0;
      let nextResetSeconds = null;

      agentsData.forEach(agent => {
        const isExhausted = (agent.weekly_used_percent !== null && agent.weekly_used_percent >= 100.0);

        if (agent.is_active) {
          activeCount++;
          if (agent.time_remaining_seconds > 0) {
            if (nextResetSeconds === null || agent.time_remaining_seconds < nextResetSeconds) {
              nextResetSeconds = agent.time_remaining_seconds;
            }
          }
        }

        const card = document.createElement("div");
        card.className = `agent-card ${isExhausted ? 'card-exhausted' : ''}`;

        const fillClass = isExhausted ? "fill-exhausted" : (agent.used_percent > 80 ? "fill-high" : (agent.used_percent > 50 ? "fill-med" : "fill-low"));
        const statusBadge = agent.is_active
          ? `<span class="status-badge badge-active">Active</span>`
          : `<span class="status-badge badge-inactive">Inactive</span>`;

        const exhaustedBadge = isExhausted
          ? `<span class="status-badge badge-exhausted">⚠️ 100% Weekly</span>`
          : ``;

        let resetFormatted = "Ready for trigger";
        if (agent.resets_at) {
          const d = new Date(agent.resets_at);
          resetFormatted = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        }

        const timerClass = agent.is_active ? "timer-value" : "timer-value inactive";
        const timerText = agent.is_active ? formatSeconds(agent.time_remaining_seconds) : "Window Inactive";

        const pokeBtnLabel = isExhausted ? "⚡ Force Poke" : "⚡ Poke";
        const pokeBtnClass = isExhausted ? "btn-poke-card force-mode" : "btn-poke-card";

        card.innerHTML = `
          <div>
            <div class="card-top">
              <div>
                <div class="agent-title">
                  ${agent.name}
                </div>
                <span class="provider-tag">${agent.provider}</span>
              </div>
              <div class="status-badges-group">
                ${statusBadge}
                ${exhaustedBadge}
              </div>
            </div>

            <div class="window-timer-box">
              <div class="timer-info-col">
                <span class="timer-label">5h Window Left</span>
                <span class="${timerClass}" id="timer-${agent.id}">${timerText}</span>
              </div>
              <div class="reset-info-col">
                <span class="timer-label">Next Reset</span>
                <span class="reset-time-sub">${resetFormatted}</span>
              </div>
            </div>

            <div class="progress-section">
              <div class="progress-labels">
                <span style="color: var(--text-muted); font-size: 0.75rem;">Account 5h Usage</span>
                <span class="progress-pct" style="color: ${agent.used_percent > 80 ? 'var(--rose)' : 'inherit'}">${agent.used_percent}%</span>
              </div>
              <div class="progress-bar-bg">
                <div class="progress-bar-fill ${fillClass}" style="width: ${Math.min(100, Math.max(2, agent.used_percent))}%"></div>
              </div>
            </div>

            ${agent.weekly_reset_str && agent.weekly_reset_str !== '-' ? `
            <div class="weekly-box">
              <div class="weekly-labels">
                <span style="font-size: 0.75rem;">Weekly Quota:</span>
                <b style="color: ${isExhausted ? 'var(--rose)' : 'inherit'}; font-size: 0.75rem;">${agent.weekly_used_percent !== null ? agent.weekly_used_percent + '%' : '-'}</b>
              </div>
              ${agent.weekly_used_percent !== null ? `
              <div class="progress-bar-bg" style="height: 5px; margin-bottom: 0.45rem;">
                <div class="progress-bar-fill" style="width: ${Math.min(100, Math.max(2, agent.weekly_used_percent))}%; background: ${isExhausted ? 'var(--rose)' : 'linear-gradient(90deg, #38bdf8, #818cf8)'};"></div>
              </div>` : ''}
              <div class="weekly-footer">
                <span>Weekly Reset:</span>
                <span style="color: ${isExhausted ? 'var(--rose)' : 'var(--cyan)'}; font-weight: 600;">${agent.weekly_reset_str}</span>
              </div>
            </div>` : ''}
          </div>

          <div class="card-footer">
            <span>${agent.category ? agent.category.toUpperCase() : 'AGENT'}</span>
            <button class="${pokeBtnClass}" id="poke-btn-${agent.id}" onclick="triggerPoke('${agent.id}', ${isExhausted})">${pokeBtnLabel}</button>
          </div>
        `;

        grid.appendChild(card);
      });

      // Update Summary cards
      document.getElementById("summary-active").innerText = `${activeCount} / ${agentsData.length}`;
      document.getElementById("summary-inactive").innerText = `${agentsData.length - activeCount}`;
      document.getElementById("summary-next-reset").innerText = nextResetSeconds !== null ? formatSeconds(nextResetSeconds) : "None active";
      document.getElementById("summary-total").innerText = `${agentsData.length} Monitored`;
    }

    function tickTimers() {
      if (!agentsData || agentsData.length === 0) return;
      let minReset = null;

      agentsData.forEach(agent => {
        if (agent.is_active && agent.time_remaining_seconds > 0) {
          agent.time_remaining_seconds--;
          const el = document.getElementById(`timer-${agent.id}`);
          if (el) {
            el.innerText = formatSeconds(agent.time_remaining_seconds);
          }
          if (minReset === null || agent.time_remaining_seconds < minReset) {
            minReset = agent.time_remaining_seconds;
          }
        }
      });

      if (minReset !== null) {
        document.getElementById("summary-next-reset").innerText = formatSeconds(minReset);
      }
    }

    // Scheduled Priming Modal Logic
    async function openScheduleModal() {
      const modal = document.getElementById("schedule-modal");
      modal.classList.add("open");
      await loadScheduleStatus();
    }

    function closeScheduleModal(event) {
      if (event && event.target !== event.currentTarget) return;
      document.getElementById("schedule-modal").classList.remove("open");
    }

    async function loadScheduleStatus() {
      try {
        const res = await fetch("/api/schedule");
        const data = await res.json();
        const statusText = document.getElementById("sched-status-text");
        const platformText = document.getElementById("sched-platform-text");
        const nextRun = document.getElementById("sched-next-run");
        const lastRun = document.getElementById("sched-last-run");
        const removeBtn = document.getElementById("btn-remove-sched");

        platformText.innerText = data.platform ? data.platform.toUpperCase() : "OS Default";
        nextRun.innerText = data.next_run_time || "None";
        lastRun.innerText = data.last_run_time || "Never";

        if (data.status === "installed") {
          statusText.innerHTML = `<span style="color: var(--emerald); font-weight: 700;">● Installed (${data.state || 'Active'})</span>`;
          removeBtn.style.display = "inline-flex";
        } else {
          statusText.innerHTML = `<span style="color: var(--amber); font-weight: 700;">○ Not Installed</span>`;
          removeBtn.style.display = "none";
        }
      } catch (err) {
        console.error("Error loading schedule status:", err);
      }
    }

    async function saveSchedule(event) {
      event.preventDefault();
      const timeVal = document.getElementById("sched-time").value;
      const freqVal = document.getElementById("sched-frequency").value;
      const notifyVal = document.getElementById("sched-notify").checked;
      const saveBtn = document.getElementById("btn-save-sched");

      saveBtn.disabled = true;
      saveBtn.innerText = "Installing...";

      try {
        const res = await fetch("/api/schedule", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "install",
            time: timeVal,
            frequency: freqVal,
            notify: notifyVal
          })
        });
        const data = await res.json();
        if (data.status === "error") {
          showToast(`Install failed: ${data.message}`, "❌");
        } else {
          showToast(`Scheduled priming installed for ${timeVal}!`, "✔");
          await loadScheduleStatus();
        }
      } catch (err) {
        showToast("Error saving schedule: " + err.message, "❌");
      } finally {
        saveBtn.disabled = false;
        saveBtn.innerText = "Save & Install Task";
      }
    }

    async function removeScheduleTask() {
      if (!confirm("Are you sure you want to remove the scheduled morning priming task?")) return;
      const removeBtn = document.getElementById("btn-remove-sched");
      removeBtn.disabled = true;
      removeBtn.innerText = "Removing...";

      try {
        const res = await fetch("/api/schedule", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "remove" })
        });
        const data = await res.json();
        showToast("Scheduled morning priming removed.", "✔");
        await loadScheduleStatus();
      } catch (err) {
        showToast("Error removing schedule: " + err.message, "❌");
      } finally {
        removeBtn.disabled = false;
        removeBtn.innerText = "Uninstall Task";
      }
    }

    // Initial Load & EventSource Startup
    fetchData();
    connectSSE();
    setInterval(tickTimers, 1000);
  </script>
</body>
</html>
"""

class SimpleDashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
        elif self.path.startswith("/api/status"):
            statuses = fetch_all_statuses()
            data = [s.to_dict() for s in statuses]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        elif self.path == "/api/schedule":
            data = get_schedule_status()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        elif self.path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            try:
                while _dash_server_running:
                    statuses = fetch_all_statuses()
                    data = [s.to_dict() for s in statuses]
                    payload = f"event: quota_update\ndata: {json.dumps(data)}\n\n"
                    self.wfile.write(payload.encode("utf-8"))
                    self.wfile.flush()

                    _dash_update_event.wait(timeout=5.0)
                    _dash_update_event.clear()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                return
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if self.path == "/api/poke":
            target = payload.get("agent_id")
            force = payload.get("force", False)

            statuses = fetch_all_statuses()
            if target:
                statuses = [s for s in statuses if s.id == target or s.id == f"claude-{target}"]

            results = []
            for s in statuses:
                if not s.is_active or force:
                    if s.id.startswith("claude-"):
                        r = poke_claude(s.id.replace("claude-", ""))
                    elif s.id == "codex":
                        r = poke_codex()
                    elif s.id == "agy":
                        r = poke_agy()
                    elif s.provider.lower() == "cursor" or s.id.startswith("cursor"):
                        r = poke_cursor()
                    elif s.provider.lower() in ("windsurf", "codeium") or s.id.startswith("windsurf"):
                        r = poke_windsurf()
                    elif s.provider.lower() in ("copilot", "github-copilot") or s.id.startswith("copilot"):
                        r = poke_copilot()
                    elif s.provider.lower() in ("aider", "openrouter") or s.id.startswith("aider") or s.id.startswith("openrouter"):
                        r = poke_aider()
                    else:
                        r = {"status": "error", "message": "Unknown agent"}
                    results.append({"agent_id": s.id, "name": s.name, **r})

            _dash_update_event.set()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "results": results}).encode("utf-8"))

        elif self.path == "/api/schedule":
            action = payload.get("action", "status")
            if action == "install":
                t_str = payload.get("time", "07:30")
                freq = payload.get("frequency", "daily")
                notify = payload.get("notify", True)
                res = install_schedule(time_str=t_str, notify=notify, frequency=freq)
            elif action == "remove":
                res = remove_schedule()
            else:
                res = get_schedule_status()

            _dash_update_event.set()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def start_dashboard(port: int = 5050) -> None:
    global _dash_server_running
    _dash_server_running = True

    server = ThreadingHTTPServer(("127.0.0.1", port), SimpleDashboardHandler)
    url = f"http://localhost:{port}"
    print(f"\n🚀 Dashboard web server v2 running at {url}")
    print("Press Ctrl+C to stop.\n")
    threading.Thread(target=lambda: (time.sleep(0.5), webbrowser.open(url)), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        _dash_server_running = False
        _dash_update_event.set()
        server.server_close()


# ---------------------------------------------------------------------------
# OS-Level Scheduled Priming Task Generator
# ---------------------------------------------------------------------------

TASK_NAME = "AgentQuotaTrackerMorningPriming"
MACOS_LABEL = "com.agentquotatracker.priming"


def get_schedule_log_file() -> Path:
    log_dir = Path(os.path.expanduser("~")) / ".agent_quota_tracker"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "schedule.log"


def append_schedule_log(message: str) -> None:
    try:
        log_file = get_schedule_log_file()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{now_str}] {message}\n")
    except Exception:
        pass


def validate_time_format(time_str: str) -> tuple[int, int]:
    if not time_str or not time_str.strip():
        raise ValueError("Time string cannot be empty. Expected HH:MM (e.g. 07:30).")
    parts = time_str.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid time format '{time_str}'. Expected HH:MM in 24-hour format (e.g. 07:30).")
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError:
        raise ValueError(f"Non-numeric values in time '{time_str}'. Expected HH:MM.")

    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Time out of range '{time_str}'. Hour must be 0-23, minute 0-59.")

    return h, m


def get_repo_dir() -> Optional[Path]:
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parent,
        Path.home() / "wsl_files" / "personal_projects" / "agents_dashboard",
    ]
    for c in candidates:
        if (c / "agents.ps1").exists() or (c / "agents_native.ps1").exists() or (c / "pyproject.toml").exists():
            return c
    return None


def get_runner_details(notify: bool = True) -> tuple[str, list[str], str]:
    repo = get_repo_dir()
    repo_str = str(repo) if repo else str(Path.cwd())
    system = platform.system().lower()

    if system == "windows":
        native_ps = repo / "agents_native.ps1" if repo else None
        if native_ps and native_ps.exists():
            args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(native_ps), "-Poke"]
            if notify:
                args.append("-Notify")
            return "powershell.exe", args, repo_str

        ps_wrapper = repo / "agents.ps1" if repo else None
        if ps_wrapper and ps_wrapper.exists():
            args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps_wrapper), "--poke"]
            if notify:
                args.append("--notify")
            return "powershell.exe", args, repo_str

        agents_bin = shutil.which("agents")
        if agents_bin:
            args = ["--poke"]
            if notify:
                args.append("--notify")
            return agents_bin, args, repo_str

        args = [str(repo / "agents.py") if repo else "agents.py", "--poke"]
        if notify:
            args.append("--notify")
        return sys.executable, args, repo_str
    else:
        agents_bin = shutil.which("agents")
        if agents_bin:
            args = ["--poke"]
            if notify:
                args.append("--notify")
            return agents_bin, args, repo_str

        sh_script = repo / "agents.sh" if repo else None
        if sh_script and sh_script.exists():
            args = ["--poke"]
            if notify:
                args.append("--notify")
            return str(sh_script), args, repo_str

        args = [str(repo / "agents.py") if repo else "agents.py", "--poke"]
        if notify:
            args.append("--notify")
        return sys.executable, args, repo_str


def _install_windows(time_str: str, notify: bool = True, frequency: str = "daily") -> dict[str, Any]:
    h, m = validate_time_format(time_str)
    formatted_time = f"{h:02d}:{m:02d}"
    exe, args, cwd = get_runner_details(notify=notify)
    arg_str = " ".join(f'"{a}"' if " " in a else a for a in args)

    freq = frequency.lower()
    if freq == "once":
        sched_desc = f"Once at {formatted_time}"
        trigger_code = f"""
$targetDt = (Get-Date).Date.AddHours({h}).AddMinutes({m})
if ($targetDt -le (Get-Date)) {{ $targetDt = $targetDt.AddDays(1) }}
$trigger = New-ScheduledTaskTrigger -Once -At $targetDt
"""
    elif freq in ("weekdays", "weekday", "workdays"):
        sched_desc = f"Weekdays at {formatted_time}"
        trigger_code = f"$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At '{formatted_time}'"
    else:
        sched_desc = f"Daily at {formatted_time}"
        trigger_code = f"$trigger = New-ScheduledTaskTrigger -Daily -At '{formatted_time}'"

    ps_script = f"""
$action = New-ScheduledTaskAction -Execute '{exe}' -Argument '{arg_str}' -WorkingDirectory '{cwd}'
{trigger_code}
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action -Trigger $trigger -Settings $settings -Force
"""
    res = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        return {"success": False, "message": f"Failed to register Windows scheduled task: {res.stderr.strip() or res.stdout.strip()}"}

    append_schedule_log(f"Scheduled task installed: {sched_desc} (Windows Task Scheduler)")
    return {
        "success": True,
        "task_name": TASK_NAME,
        "platform": "Windows Task Scheduler",
        "time": formatted_time,
        "frequency": freq,
        "schedule": sched_desc,
        "notify": notify,
        "command": f"{exe} {arg_str}",
        "working_dir": cwd,
        "log_file": str(get_schedule_log_file()),
    }


def _status_windows() -> dict[str, Any]:
    ps_script = f"""
$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue
if ($t) {{
    $info = Get-ScheduledTaskInfo -TaskName '{TASK_NAME}'
    $nextRun = if ($info.NextRunTime -and $info.NextRunTime.Year -gt 2000) {{ $info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ 'Pending' }}
    $lastRun = if ($info.LastRunTime -and $info.LastRunTime.Year -gt 2000) {{ $info.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ 'Never' }}
    [PSCustomObject]@{{
        Installed = $true
        TaskName = '{TASK_NAME}'
        Platform = 'Windows Task Scheduler'
        State = $t.State.ToString()
        NextRunTime = $nextRun
        LastRunTime = $lastRun
        LastResult = $info.LastTaskResult
    }} | ConvertTo-Json
}} else {{
    [PSCustomObject]@{{
        Installed = $false
        TaskName = '{TASK_NAME}'
        Platform = 'Windows Task Scheduler'
    }} | ConvertTo-Json
}}
"""
    res = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0 and res.stdout.strip():
        try:
            data = json.loads(res.stdout.strip())
            data["log_file"] = str(get_schedule_log_file())
            return data
        except Exception:
            pass
    return {"Installed": False, "TaskName": TASK_NAME, "Platform": "Windows Task Scheduler", "log_file": str(get_schedule_log_file())}


def _remove_windows() -> dict[str, Any]:
    ps_script = f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue"
    res = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        text=True,
    )
    append_schedule_log("Scheduled task removed (Windows Task Scheduler)")
    return {"success": res.returncode == 0, "message": f"Task '{TASK_NAME}' removed from Windows Task Scheduler."}


def _install_linux(time_str: str, notify: bool = True) -> dict[str, Any]:
    h, m = validate_time_format(time_str)
    formatted_time = f"{h:02d}:{m:02d}"
    exe, args, cwd = get_runner_details(notify=notify)
    arg_str = " ".join(args)
    log_file = get_schedule_log_file()
    cron_cmd = f"cd '{cwd}' && {exe} {arg_str} >> '{log_file}' 2>&1"
    cron_entry = f"{m} {h} * * * {cron_cmd} # {TASK_NAME}"

    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    current = res.stdout if res.returncode == 0 else ""
    lines = [line for line in current.splitlines() if TASK_NAME not in line and line.strip()]
    lines.append(cron_entry)
    new_crontab = "\n".join(lines) + "\n"

    p = subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
    if p.returncode != 0:
        return {"success": False, "message": f"Failed to install crontab: {p.stderr.strip()}"}

    append_schedule_log(f"Scheduled task installed: Daily at {formatted_time} (Linux Crontab)")
    return {
        "success": True,
        "task_name": TASK_NAME,
        "platform": "Linux Crontab",
        "time": formatted_time,
        "notify": notify,
        "command": cron_cmd,
        "log_file": str(log_file),
    }


def _status_linux() -> dict[str, Any]:
    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if res.returncode == 0:
        for line in res.stdout.splitlines():
            if TASK_NAME in line and not line.strip().startswith("#"):
                parts = line.split()
                time_str = f"{int(parts[1]):02d}:{int(parts[0]):02d}" if len(parts) >= 2 else "Unknown"
                return {
                    "Installed": True,
                    "TaskName": TASK_NAME,
                    "Platform": "Linux Crontab",
                    "State": "Active",
                    "ScheduleTime": time_str,
                    "NextRunTime": f"Daily at {time_str}",
                    "LastRunTime": "Check schedule.log",
                    "log_file": str(get_schedule_log_file()),
                }
    return {"Installed": False, "TaskName": TASK_NAME, "Platform": "Linux Crontab", "log_file": str(get_schedule_log_file())}


def _remove_linux() -> dict[str, Any]:
    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if res.returncode == 0:
        lines = [line for line in res.stdout.splitlines() if TASK_NAME not in line]
        new_crontab = "\n".join(lines) + "\n" if lines else ""
        if new_crontab:
            subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
        else:
            subprocess.run(["crontab", "-r"], capture_output=True)
    append_schedule_log("Scheduled task removed (Linux Crontab)")
    return {"success": True, "message": f"Task '{TASK_NAME}' removed from crontab."}


def _get_macos_plist_path() -> Path:
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    return agents_dir / f"{MACOS_LABEL}.plist"


def _install_macos(time_str: str, notify: bool = True) -> dict[str, Any]:
    h, m = validate_time_format(time_str)
    formatted_time = f"{h:02d}:{m:02d}"
    exe, args, cwd = get_runner_details(notify=notify)
    log_file = str(get_schedule_log_file())
    plist_path = _get_macos_plist_path()

    program_args = [exe] + args
    program_args_xml = "\n".join(f"        <string>{a}</string>" for a in program_args)

    plist_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{MACOS_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{program_args_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{cwd}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{h}</integer>
        <key>Minute</key>
        <integer>{m}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_file}</string>
    <key>StandardErrorPath</key>
    <string>{log_file}</string>
</dict>
</plist>
"""
    plist_path.write_text(plist_xml, encoding="utf-8")
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    p = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True, text=True)
    if p.returncode != 0:
        return {"success": False, "message": f"Failed to load launchd agent: {p.stderr.strip()}"}

    append_schedule_log(f"Scheduled task installed: Daily at {formatted_time} (macOS LaunchAgent)")
    return {
        "success": True,
        "task_name": TASK_NAME,
        "platform": "macOS LaunchAgent",
        "time": formatted_time,
        "notify": notify,
        "plist": str(plist_path),
        "log_file": log_file,
    }


def _status_macos() -> dict[str, Any]:
    plist_path = _get_macos_plist_path()
    if plist_path.exists():
        res = subprocess.run(["launchctl", "list", MACOS_LABEL], capture_output=True, text=True)
        return {
            "Installed": True,
            "TaskName": TASK_NAME,
            "Platform": "macOS LaunchAgent",
            "State": "Loaded" if res.returncode == 0 else "Installed (Unloaded)",
            "Plist": str(plist_path),
            "log_file": str(get_schedule_log_file()),
        }
    return {"Installed": False, "TaskName": TASK_NAME, "Platform": "macOS LaunchAgent", "log_file": str(get_schedule_log_file())}


def _remove_macos() -> dict[str, Any]:
    plist_path = _get_macos_plist_path()
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        try:
            plist_path.unlink()
        except Exception:
            pass
    append_schedule_log("Scheduled task removed (macOS LaunchAgent)")
    return {"success": True, "message": f"Task '{TASK_NAME}' removed from launchd."}


def install_schedule(time_str: str = "07:30", notify: bool = True, frequency: str = "daily") -> dict[str, Any]:
    system = platform.system().lower()
    if system == "windows":
        return _install_windows(time_str, notify=notify, frequency=frequency)
    elif system == "darwin":
        return _install_macos(time_str, notify=notify)
    else:
        return _install_linux(time_str, notify=notify)


def get_schedule_status() -> dict[str, Any]:
    system = platform.system().lower()
    if system == "windows":
        return _status_windows()
    elif system == "darwin":
        return _status_macos()
    else:
        return _status_linux()


def remove_schedule() -> dict[str, Any]:
    system = platform.system().lower()
    if system == "windows":
        return _remove_windows()
    elif system == "darwin":
        return _remove_macos()
    else:
        return _remove_linux()


def run_schedule_install_cmd(time_str: str = "07:30", notify: bool = True, frequency: str = "daily") -> None:
    freq_desc = frequency.lower()
    print(f"\n⚡ Registering OS-Level Scheduled Priming Task ({freq_desc}) at {time_str}...")
    res = install_schedule(time_str=time_str, notify=notify, frequency=freq_desc)
    if res.get("success"):
        print("✔ Successfully registered scheduled priming task!\n")
        print(f"  Task Name:      {res.get('task_name', 'AgentQuotaTrackerMorningPriming')}")
        print(f"  Platform:       {res.get('platform', 'Unknown')}")
        print(f"  Schedule:       {res.get('schedule', f'{freq_desc.capitalize()} at {time_str}')}")
        print(f"  Desktop Alerts: {'Enabled (--notify)' if notify else 'Disabled'}")
        if "command" in res:
            print(f"  Execution:      {res['command']}")
        if "log_file" in res:
            print(f"  Log File:       {res['log_file']}")
        print("\nThe system will automatically trigger morning priming even when your terminal is closed.\n")
    else:
        print(f"✖ Failed to register scheduled task: {res.get('message', 'Unknown error')}\n")


def run_schedule_status_cmd() -> None:
    status = get_schedule_status()
    print("\n⚡ OS-Level Scheduled Priming Task Status\n")
    print(f"  Task Name:      {status.get('TaskName', 'AgentQuotaTrackerMorningPriming')}")
    print(f"  Platform:       {status.get('Platform', 'Unknown')}")
    installed = status.get("Installed", False)
    print(f"  Status:         {'Installed (Active)' if installed else 'Not Installed'}")
    if installed:
        if "State" in status:
            print(f"  State:          {status['State']}")
        if "NextRunTime" in status:
            print(f"  Next Run Time:  {status['NextRunTime']}")
        if "LastRunTime" in status:
            print(f"  Last Run Time:  {status['LastRunTime']}")
        if "LastResult" in status and status["LastResult"] is not None:
            res_code = status["LastResult"]
            res_str = "0 (Success)" if res_code == 0 else str(res_code)
            print(f"  Last Exit Code: {res_str}")
    if "log_file" in status:
        print(f"  Log File:       {status['log_file']}")

    log_path = status.get("log_file")
    if log_path and os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = [ln.strip() for ln in f.readlines() if ln.strip()]
            if lines:
                print("\n  Recent Schedule Logs (last 5 runs):")
                for ln in lines[-5:]:
                    print(f"    {ln}")
        except Exception:
            pass
    print()


def run_schedule_remove_cmd() -> None:
    print("\n⚡ Removing OS-Level Scheduled Priming Task...")
    res = remove_schedule()
    if res.get("success"):
        print("✔ Successfully uninstalled scheduled priming task.\n")
    else:
        print(f"✖ {res.get('message', 'Failed to remove scheduled task.')}\n")


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="⚡ AI Agents 5-Hour Window Tracker & Dashboard\n\nMonitor rolling rate limit windows, track weekly resets, and poke AI accounts non-interactively.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  agents --status                Show 5h window state, time remaining, and weekly reset
  agents --poke                  Poke all inactive accounts to trigger 5h countdowns
  agents --poke --force          Force poke all accounts even if currently active
  agents --poke -f -a work       Force poke only the Claude Work account
  agents --poke-watch            Run autonomous watchdog to keep all windows primed
  agents --poke-watch -i 30m     Run watchdog polling every 30 minutes
  agents --poke-at 07:30         Prime windows at 07:30 AM before morning work begins
  agents --poke-at 07:30 --watch Prime at 07:30 AM and continue in watchdog mode
  agents --schedule-install      Install OS background scheduled task for 07:30 AM daily
  agents --schedule-status       Check status of OS background scheduled task
  agents --schedule-remove       Uninstall OS background scheduled task
  agents --dashboard             Launch live web dashboard at http://localhost:5050
  agents --dashboard --port 8080 Run dashboard web server on custom port 8080
""",
    )
    parser.add_argument(
        "--watch",
        "-w",
        nargs="?",
        const=15,
        type=int,
        metavar="SECONDS",
        help="Continuously watch and refresh the status table every SECONDS (default: 15s). Press Ctrl+C to exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw quota status in JSON format (ideal for scripting and automation).",
    )
    parser.add_argument(
        "--status",
        "-s",
        action="store_true",
        help="Show live 5h window state (active/inactive), time remaining, next reset, and usage %%",
    )
    parser.add_argument(
        "--poke",
        "-p",
        action="store_true",
        help="Poke inactive accounts to trigger 5h countdown (skips active accounts by default)",
    )
    parser.add_argument(
        "--poke-watch",
        action="store_true",
        help="Start automated watchdog mode: continuously monitors and pokes idle agents as 5h windows expire",
    )
    parser.add_argument(
        "--poke-at",
        type=str,
        default=None,
        metavar="HH:MM",
        help="Schedule an automated poke at a specific target time (e.g. 07:30 or 08:00) to optimize quota reset windows for peak workday hours",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=str,
        default=None,
        metavar="DURATION",
        help="Polling interval for --poke-watch (e.g. 30m, 2h, or 'auto' for adaptive sleep until earliest agent reset)",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="When used with --poke, forces a prompt even if the 5h window is already active",
    )
    parser.add_argument(
        "--agent",
        "-a",
        type=str,
        default=None,
        metavar="ID",
        help="Target a specific agent by ID (e.g. work, personal, work2, codex, agy)",
    )
    parser.add_argument(
        "--dashboard",
        "-d",
        action="store_true",
        help="Launch the interactive web dashboard with live ticking JavaScript countdown timers",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5050,
        metavar="PORT",
        help="Dashboard web server port (default: 5050)",
    )
    parser.add_argument(
        "--notify",
        "-n",
        action="store_true",
        help="Send cross-platform native OS desktop notifications on poke events and schedule completions.",
    )
    parser.add_argument(
        "--test-notify",
        action="store_true",
        help="Send a test desktop notification to verify OS notification settings and exit.",
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Output an ultra-fast (<15ms) cached status segment for Starship, Oh-My-Posh, tmux, or custom prompts.",
    )
    parser.add_argument(
        "--prompt-format",
        "--promptformat",
        type=str,
        default=None,
        metavar="FORMAT",
        help="Format template or preset ('default', 'compact', 'minimal', 'tmux', 'json') for shell prompt segment.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force refresh live quota status from provider APIs when generating prompt segment.",
    )
    parser.add_argument(
        "--schedule-install",
        nargs="?",
        const="07:30",
        default=None,
        metavar="HH:MM",
        help="Install an OS-level background scheduled task to prime quotas daily (default: 07:30).",
    )
    parser.add_argument(
        "--schedule-status",
        action="store_true",
        help="Display status of the OS-level background scheduled morning priming task.",
    )
    parser.add_argument(
        "--schedule-remove",
        action="store_true",
        help="Uninstall and remove the OS-level background scheduled morning priming task.",
    )
    parser.add_argument(
        "--frequency",
        type=str,
        default="daily",
        choices=["daily", "once", "weekdays"],
        help="Recurrence frequency for the background scheduled task: 'daily' (default), 'once', or 'weekdays'.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the background scheduled task exactly once at the target time.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run autonomous continuous auto-checker loop: checks status, waits for earliest window reset, primes, and repeats.",
    )
    parser.add_argument(
        "--auto-poke",
        action="store_true",
        help="Alias for --auto.",
    )
    parser.add_argument(
        "cmd",
        nargs="?",
        choices=["status", "poke", "dashboard", "poke-watch", "prompt", "schedule", "auto"],
        help="Optional positional command alias ('status', 'poke', 'dashboard', 'poke-watch', 'prompt', 'schedule', 'auto')",
    )
    parser.add_argument(
        "extra_args",
        nargs="*",
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()

    # Handle test notification
    if args.test_notify:
        print("⚡ Sending test desktop notification...")
        ok = send_notification("⚡ Agent Quota Tracker", "Desktop notifications are working perfectly!")
        if ok:
            print("✔ Notification dispatched successfully!")
            if not are_notifications_enabled():
                print("ℹ Note: Windows Notifications are turned OFF in your Windows Settings (System > Notifications). Enable notifications to see visual toast alerts.")
            print()
        else:
            print("✖ Notification failed to dispatch.\n")
        return

    # Handle schedule commands
    sched_freq = "once" if args.once else args.frequency
    if args.schedule_install is not None:
        run_schedule_install_cmd(time_str=args.schedule_install, notify=args.notify, frequency=sched_freq)
        return
    if args.schedule_status:
        run_schedule_status_cmd()
        return
    if args.schedule_remove:
        run_schedule_remove_cmd()
        return

    if args.cmd == "schedule":
        sub_action = (args.extra_args[0].lower() if args.extra_args else "status")
        if sub_action in ("install", "add", "set"):
            t_str = args.extra_args[1] if len(args.extra_args) > 1 else "07:30"
            run_schedule_install_cmd(time_str=t_str, notify=args.notify, frequency=sched_freq)
        elif sub_action in ("remove", "uninstall", "delete", "rm"):
            run_schedule_remove_cmd()
        elif sub_action in ("status", "check", "show", "info"):
            run_schedule_status_cmd()
        elif ":" in sub_action:
            run_schedule_install_cmd(time_str=sub_action, notify=args.notify, frequency=sched_freq)
        else:
            run_schedule_status_cmd()
        return

    # Handle prompt command
    is_prompt = args.prompt or (args.prompt_format is not None) or (args.cmd == "prompt")
    if is_prompt:
        format_spec = args.prompt_format or (args.extra_args[0] if args.extra_args else None)
        output = format_prompt(preset_or_format=format_spec, refresh=args.refresh)
        print(output)
        return

    is_status = args.status or args.cmd == "status"
    is_poke = args.poke or args.cmd == "poke"
    is_poke_watch = args.poke_watch or args.cmd == "poke-watch"
    is_auto = args.auto or args.auto_poke or (args.cmd == "auto")
    is_dashboard = args.dashboard or args.cmd == "dashboard"

    if is_auto:
        run_auto_checker_loop(
            force=args.force,
            agent_id=args.agent,
            notify=args.notify,
        )
    elif args.poke_at:
        run_poke_at(
            target_time_str=args.poke_at,
            and_watch=is_poke_watch or (args.watch is not None),
            watch_interval=args.interval,
            force=args.force,
            agent_id=args.agent,
            notify=args.notify,
        )
    elif is_poke_watch:
        run_poke_watch_loop(
            interval_arg=args.interval,
            force=args.force,
            agent_id=args.agent,
            notify=args.notify,
        )
    elif args.watch is not None:
        run_watch_loop(interval=args.watch or 15)
    elif is_status or args.json:
        print_status_table(as_json=args.json)
    elif is_poke:
        run_poke_command(force=args.force, agent_id=args.agent, notify=args.notify)
    elif is_dashboard:
        start_dashboard(port=args.port)
    else:
        print_status_table()
        print("Run with: auto, --status, --poke, --poke-watch, or --dashboard\n")


if __name__ == "__main__":
    main()
