from __future__ import annotations

import abc
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from agent_quota_tracker.models import AgentStatus, PokeResult


def parse_duration(val: Optional[str | int]) -> Optional[int]:
    """Parse duration like '30m', '2h', '90s', '1h30m', or integer seconds into total seconds."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return max(1, int(val))
    s = str(val).strip().lower()
    if not s or s == "auto":
        return None
    if s.isdigit():
        return max(1, int(s))

    pattern = r"(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*(?:(\d+)\s*s)?"
    match = re.fullmatch(pattern, s)
    if match and any(match.groups()):
        h, m, sec = match.groups()
        total = (int(h or 0) * 3600) + (int(m or 0) * 60) + int(sec or 0)
        return max(1, total) if total > 0 else None
    return None


def parse_target_time(time_str: str, now_dt: Optional[datetime] = None) -> tuple[datetime, int]:
    """Parses 'HH:MM' or 'HH:MM:SS' string into the next occurrence of that local time.
    Returns (target_datetime, seconds_until_target).
    If the time has already passed today, schedules for that time tomorrow.
    """
    if not time_str or not time_str.strip():
        raise ValueError("Time string cannot be empty")
    s = time_str.strip()
    parts = s.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid time format '{time_str}'. Expected HH:MM or HH:MM:SS in 24-hour format (e.g. 07:30 or 14:00).")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except ValueError:
        raise ValueError(f"Invalid non-numeric time '{time_str}'. Expected HH:MM or HH:MM:SS.")

    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"Time values out of range in '{time_str}'. Hour must be 0-23, minute/second 0-59.")

    now = now_dt or datetime.now()
    target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if target <= now:
        target += timedelta(days=1)

    delta_secs = int((target - now).total_seconds())
    return target, delta_secs



def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "0s"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def calculate_weekly_reset(resets_at_str: Optional[str]) -> tuple[Optional[float], str]:
    if not resets_at_str:
        return None, "-"
    try:
        cleaned = resets_at_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        secs = (dt - now).total_seconds()
        if secs <= 0:
            return 0.0, "Reset due"
        hours = round(secs / 3600.0, 1)
        local_dt = dt.astimezone()
        date_str = local_dt.strftime("%a %b %d, %H:%M")
        return hours, f"in {hours}h ({date_str})"
    except Exception:
        return None, "-"


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


class BaseTracker(abc.ABC):
    @property
    @abc.abstractmethod
    def agent_id(self) -> str:
        pass

    @property
    @abc.abstractmethod
    def display_name(self) -> str:
        pass

    @property
    @abc.abstractmethod
    def provider(self) -> str:
        pass

    @property
    def category(self) -> str:
        return getattr(self, "_category", "personal")

    @abc.abstractmethod
    def get_status(self) -> AgentStatus:
        pass

    @abc.abstractmethod
    def poke(self, prompt: str = "Hello, how are you doing?", force: bool = False) -> PokeResult:
        pass
