"""High-speed shell prompt and status bar formatter.

Designed for sub-10ms execution by reading locally cached state
(~/.agent_quota_tracker/cache.json), supporting Starship, Oh-My-Posh,
tmux, and PowerShell prompts.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

from agent_quota_tracker.cache import load_cache, save_cache


def format_duration_short(seconds: int) -> str:
    """Formats seconds into compact format like '2h14m', '45m', or '0m'."""
    if seconds <= 0:
        return "0m"
    hours, remainder = divmod(seconds, 3600)
    minutes = round(remainder / 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m" if minutes > 0 else f"{hours}h"
    return f"{max(1, minutes)}m"


def compute_live_prompt_data(cache: dict[str, Any], now_ts: Optional[float] = None) -> dict[str, Any]:
    """Calculates active counts and remaining countdowns dynamically from cached timestamps."""
    if now_ts is None:
        now_ts = time.time()

    accounts = cache.get("accounts", [])
    active_accounts: list[tuple[dict[str, Any], int]] = []

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
    """Formats the quota prompt string based on the given preset or custom format template.

    Args:
        preset_or_format: 'default', 'compact', 'minimal', 'tmux', 'json',
            or a custom format template with tokens like '{active}', '{total}', '{min_remaining}'.
        cache: Optional pre-loaded cache dictionary.
        refresh: If True, forces a live query to refresh the cache.

    Returns:
        Formatted prompt string.
    """
    if refresh or cache is None:
        if not refresh:
            cache = load_cache()

        if cache is None or refresh:
            from agent_quota_tracker.core import get_all_statuses

            statuses = get_all_statuses()
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

    # Custom template string interpolation
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
