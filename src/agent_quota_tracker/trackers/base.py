from __future__ import annotations

import abc
from datetime import datetime, timezone
from typing import Optional

from agent_quota_tracker.models import AgentStatus, PokeResult


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
    if not output:
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
