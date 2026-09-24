from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


def get_state_file() -> Path:
    state_dir = Path(os.path.expanduser("~")) / ".agents_dashboard"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "state.json"


def load_state() -> dict[str, Any]:
    state_file = get_state_file()
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict[str, Any]) -> None:
    state_file = get_state_file()
    try:
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"Warning: Failed to save state to {state_file}: {e}")


def get_agent_state(agent_id: str) -> dict[str, Any]:
    state = load_state()
    return state.get(agent_id, {})


def update_agent_state(agent_id: str, updates: dict[str, Any]) -> None:
    state = load_state()
    agent_data = state.get(agent_id, {})
    agent_data.update(updates)
    state[agent_id] = agent_data
    save_state(state)
