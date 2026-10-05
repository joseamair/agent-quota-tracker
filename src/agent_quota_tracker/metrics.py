from __future__ import annotations

import re
from typing import Any


def _escape_label_value(val: Any) -> str:
    """Escapes Prometheus label value special characters (backslash, double quote, newline)."""
    if val is None:
        return ""
    s = str(val)
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _sanitize_metric_name(name: str) -> str:
    """Ensures valid Prometheus metric identifier syntax."""
    clean = re.sub(r"[^a-zA-Z0-9_:]", "_", name)
    if not clean or clean[0].isdigit():
        clean = f"m_{clean}"
    return clean


def render_prometheus_metrics(statuses: list[Any]) -> str:
    """Renders agent quota statuses into standard Prometheus text exposition format (version 0.0.4).

    Metrics exposed:
      - agent_quota_tracker_up: 1 if tracker is running
      - agent_quota_used_percent: 5-hour rolling threshold window usage percentage (0-100)
      - agent_weekly_used_percent: Weekly quota usage percentage (0-100)
      - agent_quota_remaining_fraction: 5-hour quota remaining fraction (0.0 to 1.0)
      - agent_time_remaining_seconds: Seconds remaining in active 5-hour window
      - agent_is_active: 1 if 5-hour window is active, 0 if inactive/dormant
      - agent_auth_valid: 1 if credentials/tokens are valid, 0 if expired or missing
    """
    lines: list[str] = [
        "# HELP agent_quota_tracker_up Always 1 if the agent quota tracker exporter is active.",
        "# TYPE agent_quota_tracker_up gauge",
        "agent_quota_tracker_up 1",
        "",
        "# HELP agent_quota_used_percent Rolling 5-hour window quota usage percentage (0.0 to 100.0).",
        "# TYPE agent_quota_used_percent gauge",
    ]

    for s in statuses:
        labels = _format_labels(s)
        used_val = _extract_float(s, "used_percent", 0.0)
        lines.append(f"agent_quota_used_percent{{{labels}}} {used_val:.1f}")

    lines.append("")
    lines.append("# HELP agent_weekly_used_percent Weekly quota usage percentage (0.0 to 100.0) or 0 if unmetered.")
    lines.append("# TYPE agent_weekly_used_percent gauge")
    for s in statuses:
        labels = _format_labels(s)
        wk_val = _extract_optional_float(s, "weekly_used_percent")
        val_str = f"{wk_val:.1f}" if wk_val is not None else "0.0"
        lines.append(f"agent_weekly_used_percent{{{labels}}} {val_str}")

    lines.append("")
    lines.append("# HELP agent_quota_remaining_fraction Rolling 5-hour quota remaining fraction (0.0 to 1.0).")
    lines.append("# TYPE agent_quota_remaining_fraction gauge")
    for s in statuses:
        labels = _format_labels(s)
        used_val = _extract_float(s, "used_percent", 0.0)
        frac = max(0.0, min(1.0, round(1.0 - (used_val / 100.0), 4)))
        lines.append(f"agent_quota_remaining_fraction{{{labels}}} {frac:.4f}")

    lines.append("")
    lines.append("# HELP agent_time_remaining_seconds Seconds remaining in the active 5-hour quota window.")
    lines.append("# TYPE agent_time_remaining_seconds gauge")
    for s in statuses:
        labels = _format_labels(s)
        secs = _extract_int(s, "time_remaining_seconds", 0)
        lines.append(f"agent_time_remaining_seconds{{{labels}}} {secs}")

    lines.append("")
    lines.append("# HELP agent_is_active Whether the agent has an active rolling quota window (1=active, 0=inactive).")
    lines.append("# TYPE agent_is_active gauge")
    for s in statuses:
        labels = _format_labels(s)
        is_active = 1 if _extract_bool(s, "is_active", False) else 0
        lines.append(f"agent_is_active{{{labels}}} {is_active}")

    lines.append("")
    lines.append("# HELP agent_auth_valid Whether the agent credentials and auth state are currently valid (1=valid, 0=expired/missing).")
    lines.append("# TYPE agent_auth_valid gauge")
    for s in statuses:
        labels = _format_labels(s)
        auth_status = _extract_str(s, "auth_status", "valid").lower()
        is_valid = 1 if auth_status == "valid" else 0
        lines.append(f"agent_auth_valid{{{labels}}} {is_valid}")

    lines.append("")  # Trailing newline required by Prometheus specification
    return "\n".join(lines)


def _format_labels(s: Any) -> str:
    aid = _extract_str(s, "id") or _extract_str(s, "agent_id") or "unknown"
    name = _extract_str(s, "name") or _extract_str(s, "display_name") or aid
    provider = _extract_str(s, "provider") or "unknown"
    category = _extract_str(s, "category") or "personal"

    return (
        f'agent_id="{_escape_label_value(aid)}",'
        f'agent_name="{_escape_label_value(name)}",'
        f'provider="{_escape_label_value(provider)}",'
        f'category="{_escape_label_value(category)}"'
    )


def _extract_str(obj: Any, key: str, default: str = "") -> str:
    if isinstance(obj, dict):
        return str(obj.get(key, default) or default)
    return str(getattr(obj, key, default) or default)


def _extract_bool(obj: Any, key: str, default: bool = False) -> bool:
    if isinstance(obj, dict):
        return bool(obj.get(key, default))
    return bool(getattr(obj, key, default))


def _extract_float(obj: Any, key: str, default: float = 0.0) -> float:
    try:
        if isinstance(obj, dict):
            val = obj.get(key)
        else:
            val = getattr(obj, key, None)
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _extract_optional_float(obj: Any, key: str) -> float | None:
    try:
        if isinstance(obj, dict):
            val = obj.get(key)
        else:
            val = getattr(obj, key, None)
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def _extract_int(obj: Any, key: str, default: int = 0) -> int:
    try:
        if isinstance(obj, dict):
            val = obj.get(key)
        else:
            val = getattr(obj, key, None)
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default
