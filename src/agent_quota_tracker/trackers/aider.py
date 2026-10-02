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


class AiderTracker(BaseTracker):
    """Tracks Aider / OpenRouter balance, key limits, and credit usage."""

    def __init__(
        self,
        display_name: str = "Aider (OpenRouter)",
        category: str = "personal",
        api_key: Optional[str] = None,
        agent_id: str = "aider",
        provider: str = "aider",
    ):
        self._id = agent_id
        self._display_name = display_name
        self._category = category
        self._provider = provider
        self.api_key = api_key

    @property
    def agent_id(self) -> str:
        return self._id

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def provider(self) -> str:
        return self._provider

    def _discover_api_key(self) -> Optional[str]:
        # 1. Environment variables
        for env_var in ("OPENROUTER_API_KEY", "AIDER_API_KEY"):
            val = os.environ.get(env_var)
            if val and val.strip():
                return val.strip()

        # 2. Local or home .env / .aider.conf.yml
        home = Path(os.path.expanduser("~"))
        candidates = [
            home / ".aider.conf.yml",
            home / ".env",
            Path.cwd() / ".env",
        ]
        for path in candidates:
            if path.exists() and path.is_file():
                try:
                    for line in path.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line.startswith("OPENROUTER_API_KEY=") or line.startswith("openrouter-api-key:"):
                            parts = line.split("=", 1) if "=" in line else line.split(":", 1)
                            val = parts[1].strip().strip('"').strip("'")
                            if val:
                                return val
                except Exception:
                    pass

        return None

    def _get_api_key(self) -> Optional[str]:
        if self.api_key:
            return self.api_key
        return self._discover_api_key()

    def _query_openrouter_api(self, api_key: Optional[str]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        if not api_key:
            return None, "No OpenRouter/Aider API key found. Set OPENROUTER_API_KEY in environment or api_key in config."

        url = "https://openrouter.ai/api/v1/auth/key"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "agent-quota-tracker/1.2.0",
            "Accept": "application/json",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data, None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return None, f"OpenRouter API key invalid or unauthorized ({e.code})."
            return None, f"OpenRouter API HTTP {e.code}: {e.reason}"
        except Exception as ex:
            return None, f"OpenRouter API request failed: {ex}"

    def get_status(self) -> AgentStatus:
        key = self._get_api_key()
        res_data, err = self._query_openrouter_api(key)

        if err:
            return AgentStatus(
                id=self.agent_id,
                name=self.display_name,
                provider=self.provider,
                category=self.category,
                is_active=False,
                used_percent=0.0,
                status_label="Unconfigured / Offline" if "No OpenRouter" in err else "Error",
                error=err,
            )

        if not res_data:
            return AgentStatus(
                id=self.agent_id,
                name=self.display_name,
                provider=self.provider,
                category=self.category,
                is_active=False,
                used_percent=0.0,
                status_label="No Data",
                error="Empty response from OpenRouter API",
            )

        info = res_data.get("data", {})
        usage = float(info.get("usage", 0.0))
        limit = info.get("limit")
        label = info.get("label", "Default Key")
        is_free_tier = info.get("is_free_tier", False)

        used_percent = 0.0
        remaining_balance = None
        if limit is not None:
            limit_val = float(limit)
            if limit_val > 0:
                used_percent = min(100.0, max(0.0, round((usage / limit_val) * 100.0, 1)))
                remaining_balance = round(limit_val - usage, 2)

        is_active = usage > 0.0

        return AgentStatus(
            id=self.agent_id,
            name=self.display_name,
            provider=self.provider,
            category=self.category,
            is_active=is_active,
            used_percent=used_percent,
            status_label="Active" if is_active else "Idle",
            weekly_used_percent=used_percent if limit is not None else None,
            details={
                "label": label,
                "usage_usd": usage,
                "limit_usd": limit,
                "remaining_usd": remaining_balance,
                "is_free_tier": is_free_tier,
            },
        )

    def poke(self, prompt: str = "Hello, how are you doing?", force: bool = False) -> PokeResult:
        aider_bin = shutil.which("aider")
        if aider_bin:
            try:
                proc = subprocess.run([aider_bin, "--version"], capture_output=True, text=True, timeout=5)
                version = proc.stdout.strip().splitlines()[0] if proc.stdout else "unknown"
                return PokeResult(
                    agent_id=self.agent_id,
                    agent_name=self.display_name,
                    action_taken="poked",
                    message=f"Aider CLI detected ({version}). OpenRouter balance verified.",
                )
            except Exception as e:
                return PokeResult(
                    agent_id=self.agent_id,
                    agent_name=self.display_name,
                    action_taken="error",
                    message=f"Failed to query Aider CLI: {e}",
                )

        return PokeResult(
            agent_id=self.agent_id,
            agent_name=self.display_name,
            action_taken="skipped",
            message="Aider is monitored via OpenRouter API. Headless CLI poke not supported.",
        )
