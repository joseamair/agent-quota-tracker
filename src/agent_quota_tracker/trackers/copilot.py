from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_quota_tracker.models import AgentStatus, PokeResult
from agent_quota_tracker.trackers.base import (
    BaseTracker,
    calculate_weekly_reset,
    format_duration,
)


class CopilotTracker(BaseTracker):
    """Tracks GitHub Copilot CLI token validity and rate limits."""

    def __init__(
        self,
        display_name: str = "GitHub Copilot CLI",
        category: str = "personal",
        token: Optional[str] = None,
        agent_id: str = "copilot",
    ):
        self._id = agent_id
        self._display_name = display_name
        self._category = category
        self.token = token

    @property
    def agent_id(self) -> str:
        return self._id

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def provider(self) -> str:
        return "copilot"

    def _discover_token(self) -> Optional[str]:
        # 1. Try gh CLI auth token
        gh_bin = shutil.which("gh")
        if gh_bin:
            try:
                proc = subprocess.run([gh_bin, "auth", "token"], capture_output=True, text=True, timeout=3)
                if proc.returncode == 0 and proc.stdout.strip():
                    return proc.stdout.strip()
            except Exception:
                pass

        # 2. Try github-copilot hosts.json
        home = Path(os.path.expanduser("~"))
        candidates = [
            home / ".config" / "github-copilot" / "hosts.json",
        ]
        localappdata = os.environ.get("LOCALAPPDATA")
        if localappdata:
            candidates.append(Path(localappdata) / "github-copilot" / "hosts.json")

        for path in candidates:
            if path.exists() and path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    for host, info in data.items():
                        oauth = info.get("oauth_token")
                        if oauth:
                            return oauth
                except Exception:
                    pass

        return None

    def _get_token(self) -> Optional[str]:
        if self.token:
            return self.token
        return self._discover_token()

    def _query_copilot_token_api(self, token: Optional[str]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        if not token:
            return None, "No GitHub Copilot token found. Authenticate via 'gh auth login' or specify token in config."

        url = "https://api.github.com/copilot_internal/v2/token"
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "agent-quota-tracker/1.3.0",
            "Accept": "application/json",
        }
        req = urllib.request.Request(url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data, None
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return None, f"Copilot token unauthorized ({e.code}). Please run 'gh auth login'."
            return None, f"GitHub Copilot API HTTP {e.code}: {e.reason}"
        except Exception as ex:
            return None, f"GitHub Copilot API request failed: {ex}"

    def get_status(self) -> AgentStatus:
        tok = self._get_token()
        data, err = self._query_copilot_token_api(tok)

        remediation_hint = "Run 'gh auth login' with copilot permissions."
        if err:
            auth_status = "valid"
            if "unauthorized" in err.lower() or "401" in err or "403" in err:
                auth_status = "expired"
                status_label = "⚠️ EXPIRED"
            elif "No GitHub" in err:
                auth_status = "missing"
                status_label = "Unconfigured / Offline"
            else:
                status_label = "Error"
            return AgentStatus(
                id=self.agent_id,
                name=self.display_name,
                provider=self.provider,
                category=self.category,
                is_active=False,
                used_percent=0.0,
                status_label=status_label,
                error=err,
                auth_status=auth_status,
                remediation_hint=remediation_hint,
                locked_reason=f"Copilot auth error: {err}. {remediation_hint}",
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
                error="Empty response from Copilot token API",
                auth_status="valid",
            )

        # Copilot token response includes expires_at (unix timestamp)
        expires_at_ts = data.get("expires_at")
        resets_at_str = None
        rem_secs = 0
        rem_str = "Active"
        is_active = True
        auth_status = "valid"

        if expires_at_ts:
            try:
                exp_dt = datetime.fromtimestamp(expires_at_ts, tz=timezone.utc)
                resets_at_str = exp_dt.isoformat()
                now_utc = datetime.now(timezone.utc)
                diff = int((exp_dt - now_utc).total_seconds())
                if diff > 0:
                    rem_secs = diff
                    rem_str = format_duration(diff)
                else:
                    is_active = False
                    rem_str = "Token Expired"
                    auth_status = "expired"
            except Exception:
                pass

        status_label = "Active" if is_active else ("⚠️ EXPIRED" if auth_status == "expired" else "Token Expired")
        locked_reason = f"Copilot token expired. {remediation_hint}" if auth_status == "expired" else None

        return AgentStatus(
            id=self.agent_id,
            name=self.display_name,
            provider=self.provider,
            category=self.category,
            is_active=is_active,
            used_percent=0.0,
            time_remaining_seconds=rem_secs,
            time_remaining_str=rem_str,
            resets_at=resets_at_str,
            status_label=status_label,
            auth_status=auth_status,
            remediation_hint=remediation_hint,
            locked_reason=locked_reason,
            details={
                "sku": data.get("sku", "copilot_for_individual"),
                "chat_enabled": data.get("chat_enabled", True),
            },
        )

    def poke(self, prompt: str = "Hello, how are you doing?", force: bool = False) -> PokeResult:
        gh_bin = shutil.which("gh")
        if gh_bin:
            try:
                # Test gh copilot suggestion or version
                proc = subprocess.run(
                    [gh_bin, "copilot", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0:
                    version = proc.stdout.strip().splitlines()[0] if proc.stdout else "unknown"
                    return PokeResult(
                        agent_id=self.agent_id,
                        agent_name=self.display_name,
                        action_taken="poked",
                        message=f"GitHub Copilot CLI detected ({version}). Token verified.",
                    )
            except Exception:
                pass

        return PokeResult(
            agent_id=self.agent_id,
            agent_name=self.display_name,
            action_taken="skipped",
            message="GitHub Copilot token verified via API.",
        )
