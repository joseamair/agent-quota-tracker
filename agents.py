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
import shutil
import subprocess
import sys
import threading
import time
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

    is_idle = (used_pct == 0.0 and not has_recent_poke)

    if resets_dt and resets_dt > now and not is_idle:
        is_active = True
        remaining_secs = int((resets_dt - now).total_seconds())
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

            is_idle = (used_pct == 0.0 and not has_fresh_poke)

            if r_dt and r_dt > now and not is_idle:
                is_active = True
                remaining_secs = max(0, int((r_dt - now).total_seconds()))
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
    return statuses


def run_poke_command(force: bool = False, agent_id: Optional[str] = None) -> None:
    mode_str = " (FORCE mode enabled)" if force else ""
    print(f"\n⚡ [POKE] Checking 5-hour rolling threshold windows{mode_str}...\n")
    statuses = fetch_all_statuses()
    if agent_id:
        target = agent_id.lower()
        statuses = [s for s in statuses if s.id == target or s.id == f"claude-{target}"]
        if not statuses:
            print(f"✖ Unknown agent ID '{agent_id}'. Options: work, personal, work2, codex, agy\n")
            return

    for s in statuses:
        if s.is_active and not force:
            print(f"  ↷ SKIPPED: {s.name:<25} Window already ACTIVE ({s.time_remaining_str} remaining, {s.used_percent}% used).")
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
        else:
            res = {"status": "error", "message": "Unknown agent", "reply": None, "verified_active": False}

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

    print("\nDone!\n")


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


def compute_adaptive_sleep_seconds(agents_info: list[AgentInfo]) -> tuple[int, str]:
    active_with_time = [
        a for a in agents_info
        if a.is_active and a.time_remaining_seconds > 0
    ]
    if not active_with_time:
        return 120, "All agents idle or freshly checked"

    earliest = min(active_with_time, key=lambda a: a.time_remaining_seconds)
    sleep_secs = max(60, earliest.time_remaining_seconds + 45)
    return sleep_secs, f"{earliest.name} ({format_duration(earliest.time_remaining_seconds)} left)"


def run_countdown(total_seconds: int, prefix: str) -> None:
    import time
    for rem in range(total_seconds, 0, -1):
        sys.stdout.write(f"\r  ⏳ {prefix}: {format_duration(rem)} remaining • Press Ctrl+C to stop   ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * 85 + "\r")
    sys.stdout.flush()


def run_poke_watch_loop(
    interval_arg: Optional[str] = None,
    force: bool = False,
    agent_id: Optional[str] = None,
) -> None:
    fixed_interval = parse_duration(interval_arg) if interval_arg else None
    mode_str = f"fixed {format_duration(fixed_interval)} interval" if fixed_interval else "adaptive window expiry mode"
    print(f"\n================================================================================================================================")
    print(f"  ⚡ AUTONOMOUS POKE WATCHDOG STARTED")
    print(f"  Running in {mode_str}. Automatically primes 5h quota windows as accounts cool down.")
    print(f"  Press Ctrl+C to terminate.")
    print(f"================================================================================================================================\n")

    cycle = 1
    try:
        while True:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"▶ Watchdog Cycle #{cycle} • {now_str}")
            run_poke_command(force=force, agent_id=agent_id)

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
) -> None:
    try:
        target_dt, delta_secs = parse_target_time(target_time_str)
    except ValueError as e:
        print(f"✖ Error: {e}")
        return

    target_str = target_dt.strftime("%Y-%m-%d %H:%M:%S")
    relative_day = "today" if target_dt.date() == datetime.now().date() else "tomorrow"

    print(f"\n================================================================================================================================")
    print(f"  ⚡ SCHEDULED PEAK-TIME PRIMING MODE")
    print(f"  Target Execution: {target_str} ({relative_day})")
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
    run_poke_command(force=force, agent_id=agent_id)
    print_status_table()

    if and_watch:
        print("Transitioning into automated watchdog mode...\n")
        run_poke_watch_loop(interval_arg=watch_interval, force=force, agent_id=agent_id)


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
            wk_usage = f"{s.weekly_used_percent}%" if s.weekly_used_percent is not None else "-"
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
            wk_usage = f"{int(round(s.weekly_used_percent))}%" if s.weekly_used_percent is not None else "-"
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

DASHBOARD_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AI Agents 5h Window Dashboard</title>
  <style>
    body { background: #0b0f19; color: #f1f5f9; font-family: -apple-system, system-ui, sans-serif; padding: 2rem; margin: 0; }
    .container { max-width: 1000px; margin: 0 auto; }
    h1 { margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.75rem; }
    .sub { color: #94a3b8; font-size: 0.95rem; margin-bottom: 2rem; }
    .toolbar { display: flex; gap: 1rem; margin-bottom: 1.5rem; }
    button { background: #2563eb; color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 8px; font-weight: 600; cursor: pointer; }
    button:hover { background: #1d4ed8; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.25rem; }
    .card { background: #161f30; border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 1.25rem; }
    .card-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
    .title { font-weight: 700; font-size: 1.1rem; }
    .badge { padding: 0.25rem 0.6rem; border-radius: 999px; font-size: 0.75rem; font-weight: 700; }
    .badge.active { background: rgba(16,185,129,0.2); color: #10b981; }
    .badge.inactive { background: rgba(148,163,184,0.2); color: #94a3b8; }
    .timer-box { background: rgba(0,0,0,0.3); border-radius: 8px; padding: 0.85rem; margin-bottom: 1rem; }
    .timer-num { font-size: 1.5rem; font-family: monospace; font-weight: 700; color: #38bdf8; }
    .timer-sub { font-size: 0.8rem; color: #94a3b8; margin-top: 0.2rem; }
    .bar-bg { height: 8px; background: rgba(255,255,255,0.1); border-radius: 99px; overflow: hidden; margin-top: 0.5rem; }
    .bar-fill { height: 100%; background: #10b981; border-radius: 99px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>⚡ AI Agents 5-Hour Window Tracker</h1>
    <div class="sub">Tracks 5-hour rolling threshold windows for Claude (Work, Personal, Work2), Codex, and Google Antigravity.</div>
    <div class="toolbar">
      <button onclick="fetchData()">🔄 Refresh</button>
      <button style="background: #059669;" onclick="pokeInactive()">⚡ Poke Inactive Agents</button>
    </div>
    <div class="grid" id="grid"></div>
  </div>

  <script>
    let agents = [];
    async function fetchData() {
      const res = await fetch('/api/status');
      agents = await res.json();
      render();
    }

    async function pokeInactive() {
      alert("Triggering poke on inactive agents...");
      await fetch('/api/poke', { method: 'POST' });
      fetchData();
    }

    function render() {
      const grid = document.getElementById('grid');
      grid.innerHTML = '';
      agents.forEach(a => {
        const card = document.createElement('div');
        card.className = 'card';
        const badgeClass = a.is_active ? 'badge active' : 'badge inactive';
        const badgeText = a.is_active ? 'ACTIVE' : 'INACTIVE';
        card.innerHTML = `
          <div class="card-top">
            <div class="title">${a.name}</div>
            <span class="${badgeClass}">${badgeText}</span>
          </div>
          <div class="timer-box">
            <div class="timer-num" id="t-${a.id}">${a.is_active ? a.time_remaining_str : 'Inactive'}</div>
            <div class="timer-sub">Reset: ${a.resets_at ? new Date(a.resets_at).toLocaleTimeString() : 'Ready to Poke'}</div>
          </div>
          <div style="font-size: 0.85rem; display: flex; justify-content: space-between;">
            <span>5h Quota Usage:</span>
            <b>${a.used_percent}%</b>
          </div>
          <div class="bar-bg">
            <div class="bar-fill" style="width: ${Math.max(2, a.used_percent)}%; background: ${a.used_percent > 80 ? '#f43f5e' : (a.used_percent > 50 ? '#f59e0b' : '#10b981')}"></div>
          </div>
          ${a.weekly_reset_str && a.weekly_reset_str !== '-' ? `
          <div style="margin-top: 0.85rem; padding-top: 0.65rem; border-top: 1px solid rgba(255,255,255,0.08); font-size: 0.8rem; color: #94a3b8;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.2rem;">
              <span>Weekly Quota:</span>
              <b style="color: #f1f5f9;">${a.weekly_used_percent !== null ? a.weekly_used_percent + '%' : '-'}</b>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 0.75rem;">
              <span>Week Reset:</span>
              <span style="color: #38bdf8; font-weight: 600;">${a.weekly_reset_str}</span>
            </div>
          </div>` : ''}
        `;
        grid.appendChild(card);
      });
    }

    setInterval(() => {
      agents.forEach(a => {
        if (a.is_active && a.time_remaining_seconds > 0) {
          a.time_remaining_seconds--;
          const el = document.getElementById('t-' + a.id);
          if (el) {
            const h = Math.floor(a.time_remaining_seconds / 3600);
            const m = Math.floor((a.time_remaining_seconds % 3600) / 60);
            const s = a.time_remaining_seconds % 60;
            el.innerText = `${h}h ${m}m ${s}s`;
          }
        }
      });
    }, 1000);

    fetchData();
    setInterval(fetchData, 10000);
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
        elif self.path == "/api/status":
            statuses = fetch_all_statuses()
            data = [s.to_dict() for s in statuses]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/api/poke":
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
            try:
                payload = json.loads(body)
            except Exception:
                payload = {}

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
                    else:
                        r = {"status": "error", "message": "Unknown agent"}
                    results.append({"agent_id": s.id, "name": s.name, **r})

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "results": results}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def start_dashboard(port: int = 5050) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), SimpleDashboardHandler)
    url = f"http://localhost:{port}"
    print(f"\n🚀 Dashboard web server running at {url}")
    print("Press Ctrl+C to stop.\n")
    threading.Thread(target=lambda: (time.sleep(0.5), webbrowser.open(url)), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


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
        "cmd",
        nargs="?",
        choices=["status", "poke", "dashboard", "poke-watch"],
        help="Optional positional command alias ('status', 'poke', 'dashboard', 'poke-watch')",
    )

    args = parser.parse_args()

    is_status = args.status or args.cmd == "status"
    is_poke = args.poke or args.cmd == "poke"
    is_poke_watch = args.poke_watch or args.cmd == "poke-watch"
    is_dashboard = args.dashboard or args.cmd == "dashboard"

    if args.poke_at:
        run_poke_at(
            target_time_str=args.poke_at,
            and_watch=is_poke_watch or (args.watch is not None),
            watch_interval=args.interval,
            force=args.force,
            agent_id=args.agent,
        )
    elif is_poke_watch:
        run_poke_watch_loop(
            interval_arg=args.interval,
            force=args.force,
            agent_id=args.agent,
        )
    elif args.watch is not None:
        run_watch_loop(interval=args.watch or 15)
    elif is_status or args.json:
        print_status_table(as_json=args.json)
    elif is_poke:
        run_poke_command(force=args.force, agent_id=args.agent)
    elif is_dashboard:
        start_dashboard(port=args.port)
    else:
        print_status_table()
        print("Run with: --status, --poke, --poke-watch, or --dashboard\n")


if __name__ == "__main__":
    main()
