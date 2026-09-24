from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class AgentStatus:
    id: str
    name: str
    provider: str  # 'claude', 'codex', 'agy'
    is_active: bool
    used_percent: float
    resets_at: Optional[str] = None
    resets_at_timestamp: Optional[float] = None
    time_remaining_seconds: int = 0
    time_remaining_str: str = "Inactive"
    window_duration_mins: int = 300  # Default 5h
    status_label: str = "Inactive"
    weekly_used_percent: Optional[float] = None
    weekly_resets_at: Optional[str] = None
    weekly_remaining_hours: Optional[float] = None
    weekly_reset_str: str = "-"
    category: str = "personal"  # 'personal' or 'work'
    last_poked_at: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "category": self.category,
            "is_active": self.is_active,
            "used_percent": round(self.used_percent, 1),
            "resets_at": self.resets_at,
            "resets_at_timestamp": self.resets_at_timestamp,
            "time_remaining_seconds": self.time_remaining_seconds,
            "time_remaining_str": self.time_remaining_str,
            "window_duration_mins": self.window_duration_mins,
            "status_label": self.status_label,
            "weekly_used_percent": round(self.weekly_used_percent, 1) if self.weekly_used_percent is not None else None,
            "weekly_resets_at": self.weekly_resets_at,
            "weekly_remaining_hours": self.weekly_remaining_hours,
            "weekly_reset_str": self.weekly_reset_str,
            "last_poked_at": self.last_poked_at,
            "error": self.error,
        }


@dataclass
class PokeResult:
    agent_id: str
    agent_name: str
    action_taken: str  # 'poked', 'skipped', 'error', 'unverified'
    message: str
    reply: Optional[str] = None
    verified_active: bool = False
    time_remaining_str: Optional[str] = None
    used_percent: Optional[float] = None
    details: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "action_taken": self.action_taken,
            "message": self.message,
            "reply": self.reply,
            "verified_active": self.verified_active,
            "time_remaining_str": self.time_remaining_str,
            "used_percent": self.used_percent,
            "details": self.details,
        }
