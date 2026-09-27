"""Local disk cache for fast agent quota prompt and status queries.

Stores serialized agent quota status in ~/.agent_quota_tracker/cache.json
allowing sub-10ms prompt segment evaluations without API calls.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_quota_tracker.models import AgentStatus


def get_cache_dir() -> Path:
    """Returns the primary cache directory ~/.agent_quota_tracker."""
    d = Path(os.path.expanduser("~")) / ".agent_quota_tracker"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_cache_file() -> Path:
    """Returns the path to the cache.json file, checking standard locations."""
    p1 = Path(os.path.expanduser("~")) / ".agent_quota_tracker" / "cache.json"
    p2 = Path(os.path.expanduser("~")) / ".agents_dashboard" / "cache.json"
    if p1.exists():
        return p1
    if p2.exists():
        return p2
    p1.parent.mkdir(parents=True, exist_ok=True)
    return p1


def save_cache(statuses: list[AgentStatus]) -> None:
    """Serializes the list of AgentStatus objects to cache.json."""
    cache_file = get_cache_file()
    now_ts = time.time()
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()

    accounts_data = [s.to_dict() for s in statuses]
    active_count = sum(1 for s in statuses if s.is_active)

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
    except Exception as e:
        # Saving cache should never crash the caller
        try:
            cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass


def load_cache() -> Optional[dict[str, Any]]:
    """Loads cached quota state from disk, or returns None if unavailable."""
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
