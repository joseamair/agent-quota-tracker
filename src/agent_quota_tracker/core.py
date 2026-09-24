from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from agent_quota_tracker.models import AgentStatus, PokeResult
from agent_quota_tracker.trackers.agy import AGYTracker
from agent_quota_tracker.trackers.base import BaseTracker
from agent_quota_tracker.trackers.claude import ClaudeTracker
from agent_quota_tracker.trackers.codex import CodexTracker

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
    """Loads accounts from agents.config.json or falls back to standard accounts."""
    candidates = [
        Path.cwd() / "agents.config.json",
        Path(__file__).resolve().parent.parent.parent / "agents.config.json",
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


def get_default_trackers() -> list[BaseTracker]:
    accounts = load_accounts_config()
    trackers: list[BaseTracker] = []
    for acc in accounts:
        prov = acc.get("provider", "").lower()
        aid = acc.get("id", "")
        name = acc.get("name") or aid
        category = acc.get("category", "personal")
        if prov == "agy":
            trackers.append(AGYTracker(name, category=category))
        elif prov == "codex":
            trackers.append(CodexTracker(name, category=category))
        elif prov == "claude":
            prof = acc.get("profile") or aid
            trackers.append(ClaudeTracker(prof, name, category=category))
    return trackers


def get_all_statuses() -> list[AgentStatus]:
    trackers = get_default_trackers()

    # Query concurrently for fast response
    with ThreadPoolExecutor(max_workers=max(1, len(trackers))) as executor:
        statuses = list(executor.map(lambda t: t.get_status(), trackers))

    return statuses


def poke_all(
    force: bool = False,
    agent_id: Optional[str] = None,
    prompt: str = "Hello, how are you doing?",
) -> list[PokeResult]:
    trackers = get_default_trackers()
    if agent_id:
        target = agent_id.lower()
        trackers = [t for t in trackers if t.agent_id == target or t.agent_id == f"claude-{target}"]

    results: list[PokeResult] = []
    for t in trackers:
        if not force:
            st = t.get_status()
            if st.is_active:
                results.append(
                    PokeResult(
                        agent_id=t.agent_id,
                        agent_name=t.display_name,
                        action_taken="skipped",
                        message=f"5h window is already active ({st.time_remaining_str} remaining, {st.used_percent}% used). Skipped poke.",
                    )
                )
                continue

        res = t.poke(prompt=prompt, force=force)
        results.append(res)

    return results
