from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from agent_quota_tracker.models import AgentStatus, PokeResult
from agent_quota_tracker.trackers.base import (
    BaseTracker,
    calculate_weekly_reset,
)


class WindsurfTracker(BaseTracker):
    """Tracks Windsurf (Cascade / Codeium) quota and credits."""

    def __init__(
        self,
        display_name: str = "Windsurf (Cascade)",
        category: str = "personal",
        api_key: Optional[str] = None,
        agent_id: str = "windsurf",
    ):
        self._id = agent_id
        self._display_name = display_name
        self._category = category
        self.api_key = api_key

    @property
    def agent_id(self) -> str:
        return self._id

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def provider(self) -> str:
        return "windsurf"

    def _discover_api_key(self) -> Optional[str]:
        """Attempts to discover Codeium/Windsurf API key from config files."""
        home = Path(os.path.expanduser("~"))
        candidates: list[Path] = [
            home / ".codeium" / "config.json",
            home / ".codeium" / "windsurf" / "mcp_config.json",
        ]
        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            candidates.append(Path(user_profile) / ".codeium" / "config.json")

        for path in candidates:
            if path.exists() and path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    key = data.get("apiKey") or data.get("api_key") or data.get("token")
                    if key and isinstance(key, str) and key.strip():
                        return key.strip()
                except Exception:
                    pass
        return None

    def _get_api_key(self) -> Optional[str]:
        if self.api_key:
            return self.api_key
        for env_var in ("CODEIUM_API_KEY", "WINDSURF_API_KEY", "CODEIUM_TOKEN"):
            val = os.environ.get(env_var)
            if val and val.strip():
                return val.strip()
        return self._discover_api_key()

    def _query_status_api(self, api_key: Optional[str]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        if not api_key:
            return None, "No Windsurf/Codeium API key found. Set api_key in config or login to Windsurf."

        # Codeium / Windsurf user metadata endpoint
        url = "https://api.codeium.com/register_user/"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "agent-quota-tracker/1.4.0",
        }
        payload = json.dumps({"api_key": api_key}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data, None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return None, f"Windsurf API key unauthorized or expired ({e.code})."
            return None, f"Windsurf API HTTP {e.code}: {e.reason}"
        except Exception as ex:
            return None, f"Windsurf API request failed: {ex}"

    def get_status(self) -> AgentStatus:
        key = self._get_api_key()
        data, err = self._query_status_api(key)

        if err:
            return AgentStatus(
                id=self.agent_id,
                name=self.display_name,
                provider=self.provider,
                category=self.category,
                is_active=False,
                used_percent=0.0,
                status_label="Unconfigured / Offline" if "No Windsurf" in err else "Error",
                error=err,
            )

        if not data:
            return AgentStatus(
                id=self.agent_id,
                name=self.display_name,
                provider=self.provider,
                category=self.category,
                is_active=False,
                used_percent=0.0,
                status_label="No Data",
                error="Empty response from Windsurf API",
            )

        # Parse user credits / status if available
        user_info = data.get("user") or data
        plan = user_info.get("plan_type", "Standard")
        used_percent = float(user_info.get("used_percent", 0.0))

        return AgentStatus(
            id=self.agent_id,
            name=self.display_name,
            provider=self.provider,
            category=self.category,
            is_active=used_percent > 0.0,
            used_percent=used_percent,
            status_label="Active" if used_percent > 0.0 else "Idle",
            weekly_used_percent=used_percent,
            details={"plan": plan, "raw": user_info},
        )

    def poke(self, prompt: str = "Hello, how are you doing?", force: bool = False) -> PokeResult:
        windsurf_bin = shutil.which("windsurf")
        if windsurf_bin:
            try:
                proc = subprocess.run([windsurf_bin, "--version"], capture_output=True, text=True, timeout=5)
                version = proc.stdout.strip().splitlines()[0] if proc.stdout else "unknown"
                return PokeResult(
                    agent_id=self.agent_id,
                    agent_name=self.display_name,
                    action_taken="poked",
                    message=f"Windsurf IDE detected (version {version}). Monitored via API.",
                )
            except Exception as e:
                return PokeResult(
                    agent_id=self.agent_id,
                    agent_name=self.display_name,
                    action_taken="error",
                    message=f"Failed to query Windsurf CLI: {e}",
                )

        return PokeResult(
            agent_id=self.agent_id,
            agent_name=self.display_name,
            action_taken="skipped",
            message="Windsurf is monitored via API. Headless CLI poke not supported.",
        )
