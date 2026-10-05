from __future__ import annotations

import json
import os
import shutil
import sqlite3
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


class CursorTracker(BaseTracker):
    """Tracks Cursor (Composer / Fast Requests) quota and subscription usage."""

    def __init__(
        self,
        display_name: str = "Cursor Composer",
        category: str = "personal",
        access_token: Optional[str] = None,
        cookie: Optional[str] = None,
        agent_id: str = "cursor",
        db_path: Optional[Path] = None,
    ):
        self._id = agent_id
        self._display_name = display_name
        self._category = category
        self.access_token = access_token
        self.cookie = cookie or os.environ.get("CURSOR_SESSION_COOKIE") or os.environ.get("WORKOS_CURSOR_SESSION_TOKEN")
        self.db_path = db_path

    @property
    def agent_id(self) -> str:
        return self._id

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def provider(self) -> str:
        return "cursor"

    def _discover_token_from_sqlite(self) -> Optional[str]:
        """Attempts to discover the Cursor access token from local state.vscdb."""
        if self.db_path and self.db_path.exists():
            candidates: list[Path] = [self.db_path]
        else:
            home = Path(os.path.expanduser("~"))
            candidates: list[Path] = []

            appdata = os.environ.get("APPDATA")
            if appdata:
                candidates.append(Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb")

            # macOS candidate
            candidates.append(home / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "state.vscdb")
            # Linux candidate
            candidates.append(home / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb")

        for db_path in candidates:
            if db_path.exists() and db_path.is_file():
                try:
                    # Open read-only URI to avoid locking issues
                    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=2.0)
                    cur = conn.cursor()
                    cur.execute("SELECT value FROM ItemTable WHERE key = 'cursorAuth/accessToken' LIMIT 1")
                    row = cur.fetchone()
                    conn.close()
                    if row and row[0]:
                        token = str(row[0]).strip().strip('"').strip("'")
                        if token:
                            return token
                except Exception:
                    pass
        return None

    def _get_token(self) -> Optional[str]:
        if self.access_token:
            return self.access_token
        for env_var in ("CURSOR_ACCESS_TOKEN", "CURSOR_TOKEN"):
            val = os.environ.get(env_var)
            if val and val.strip():
                return val.strip()
        return self._discover_token_from_sqlite()

    def _query_usage_api(self, token: Optional[str]) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        """Queries the Cursor usage endpoint. Returns (data, error_message)."""
        headers: dict[str, str] = {
            "User-Agent": "agent-quota-tracker/1.3.0",
            "Accept": "application/json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if self.cookie:
            headers["Cookie"] = f"WorkosCursorSessionToken={self.cookie}"

        if not token and not self.cookie:
            return None, "No Cursor access token or session cookie found. Configure access_token in config or login to Cursor."

        # Prefer api2.cursor.sh/auth/usage if bearer token is available
        url = "https://api2.cursor.sh/auth/usage" if token else "https://www.cursor.com/api/usage"

        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data, None
        except urllib.error.HTTPError as e:
            if e.code == 401 or e.code == 403:
                return None, f"Cursor token expired or unauthorized ({e.code}). Please re-login to Cursor."
            return None, f"Cursor API HTTP {e.code}: {e.reason}"
        except Exception as ex:
            return None, f"Cursor API request failed: {ex}"

    def get_status(self) -> AgentStatus:
        token = self._get_token()
        data, err = self._query_usage_api(token)

        if err:
            auth_status = "valid"
            remediation_hint = None
            if "401" in err or "403" in err:
                auth_status = "expired"
                remediation_hint = "Open Cursor editor to refresh session."
                status_label = "⚠️ EXPIRED"
            elif "No Cursor" in err or "token" in err.lower():
                auth_status = "missing"
                remediation_hint = "Open Cursor or set access_token in agents.config.json."
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
                locked_reason=f"Cursor auth issue ({err}). {remediation_hint}" if remediation_hint else None,
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
                error="Empty response from Cursor usage API",
                auth_status="valid",
            )

        # Parse usage data: common keys include 'gpt-4', 'claude-3.5-sonnet', or 'fastRequests'
        num_requests = 0
        max_requests = 500
        start_of_month = data.get("startOfMonth")

        for key in ("gpt-4", "claude-3.5-sonnet", "fastRequests", "regularRequests"):
            model_info = data.get(key)
            if isinstance(model_info, dict):
                num_requests = model_info.get("numRequests", num_requests)
                max_requests = model_info.get("maxRequestUsage", max_requests)
                break

        used_percent = (num_requests / max_requests * 100.0) if max_requests > 0 else 0.0
        used_percent = min(100.0, max(0.0, round(used_percent, 1)))

        # Weekly/Monthly reset calculation
        wk_hours, wk_str = calculate_weekly_reset(start_of_month)

        return AgentStatus(
            id=self.agent_id,
            name=self.display_name,
            provider=self.provider,
            category=self.category,
            is_active=used_percent > 0.0,
            used_percent=used_percent,
            status_label="Active" if used_percent > 0.0 else "Idle",
            weekly_used_percent=used_percent,
            weekly_resets_at=start_of_month,
            weekly_remaining_hours=wk_hours,
            weekly_reset_str=wk_str,
            details={
                "num_requests": num_requests,
                "max_requests": max_requests,
                "start_of_month": start_of_month,
            },
        )

    def poke(self, prompt: str = "Hello, how are you doing?", force: bool = False) -> PokeResult:
        cursor_bin = shutil.which("cursor")
        if cursor_bin:
            try:
                proc = subprocess.run([cursor_bin, "--version"], capture_output=True, text=True, timeout=5)
                version = proc.stdout.strip().splitlines()[0] if proc.stdout else "unknown"
                return PokeResult(
                    agent_id=self.agent_id,
                    agent_name=self.display_name,
                    action_taken="poked",
                    message=f"Cursor IDE detected (version {version}). Monitored via API.",
                )
            except Exception as e:
                return PokeResult(
                    agent_id=self.agent_id,
                    agent_name=self.display_name,
                    action_taken="error",
                    message=f"Failed to query Cursor CLI: {e}",
                )

        return PokeResult(
            agent_id=self.agent_id,
            agent_name=self.display_name,
            action_taken="skipped",
            message="Cursor is monitored via API. Headless CLI poke not supported.",
        )
