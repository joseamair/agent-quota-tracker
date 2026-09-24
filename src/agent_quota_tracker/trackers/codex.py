from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from agent_quota_tracker.models import AgentStatus, PokeResult
from agent_quota_tracker.state import get_agent_state, update_agent_state
from agent_quota_tracker.trackers.base import (
    BaseTracker,
    calculate_weekly_reset,
    extract_reply_snippet,
    format_duration,
)


class CodexTracker(BaseTracker):
    def __init__(self, display_name: str = "OpenAI Codex", category: str = "personal"):
        self._display_name = display_name
        self._category = category
        self.home = Path(os.path.expanduser("~"))

    @property
    def agent_id(self) -> str:
        return "codex"

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def provider(self) -> str:
        return "codex"

    def _query_app_server_limits(self, timeout_sec: float = 4.0) -> Optional[dict[str, Any]]:
        codex_bin = shutil.which("codex") or shutil.which("codex.cmd")
        if not codex_bin:
            return None

        proc = None
        try:
            proc = subprocess.Popen(
                [codex_bin, "app-server", "--stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )

            # Send initialize
            init_req = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"clientInfo": {"name": "agents-dashboard", "version": "0.1.0"}},
            }
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(init_req) + "\n")
            proc.stdin.flush()

            # Read init response
            _ = proc.stdout.readline()

            # Request rateLimits
            limits_req = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "account/rateLimits/read",
                "params": {},
            }
            proc.stdin.write(json.dumps(limits_req) + "\n")
            proc.stdin.flush()

            start_t = time.time()
            while time.time() - start_t < timeout_sec:
                line = proc.stdout.readline()
                if not line:
                    break
                try:
                    data = json.loads(line)
                    if data.get("id") == 2 and "result" in data:
                        return data["result"]
                except Exception:
                    continue

        except Exception:
            return None
        finally:
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass

        return None

    def get_status(self) -> AgentStatus:
        agent_st = get_agent_state(self.agent_id)
        last_poked_at = agent_st.get("last_poked_at")

        result = self._query_app_server_limits()
        if not result or "rateLimits" not in result:
            return AgentStatus(
                id=self.agent_id,
                name=self.display_name,
                provider=self.provider,
                is_active=False,
                used_percent=0.0,
                status_label="Unable to query Codex",
                last_poked_at=last_poked_at,
                error="Could not connect to codex app-server",
            )

        rl = result.get("rateLimits", {})
        primary = rl.get("primary") or {}
        secondary = rl.get("secondary") or {}

        used_pct = float(primary.get("usedPercent") or 0.0)
        resets_at_ts = primary.get("resetsAt")
        window_mins = int(primary.get("windowDurationMins") or 300)

        now_ts = time.time()
        is_active = False
        remaining_seconds = 0
        resets_at_str = None

        if resets_at_ts is not None:
            resets_dt = datetime.fromtimestamp(resets_at_ts, tz=timezone.utc)
            resets_at_str = resets_dt.isoformat()

            if resets_at_ts > now_ts:
                is_active = True
                remaining_seconds = max(0, int(resets_at_ts - now_ts))
                status_label = "Active"
            else:
                is_active = False
                remaining_seconds = 0
                status_label = "Inactive (Ready to Poke)"
                used_pct = 0.0
        else:
            status_label = "Inactive (No window active)"
            used_pct = 0.0

        # Weekly stats
        weekly_used_pct = float(secondary.get("usedPercent")) if secondary.get("usedPercent") is not None else None
        weekly_resets_at = None
        weekly_hours = None
        weekly_reset_str = "-"
        if secondary.get("resetsAt"):
            weekly_resets_at = datetime.fromtimestamp(secondary["resetsAt"], tz=timezone.utc).isoformat()
            weekly_hours, weekly_reset_str = calculate_weekly_reset(weekly_resets_at)

        return AgentStatus(
            id=self.agent_id,
            name=self.display_name,
            provider=self.provider,
            is_active=is_active,
            used_percent=used_pct,
            resets_at=resets_at_str,
            resets_at_timestamp=float(resets_at_ts) if resets_at_ts else None,
            time_remaining_seconds=remaining_seconds,
            time_remaining_str=format_duration(remaining_seconds) if is_active else "Inactive",
            window_duration_mins=window_mins,
            status_label=status_label,
            weekly_used_percent=weekly_used_pct,
            weekly_resets_at=weekly_resets_at,
            weekly_remaining_hours=weekly_hours,
            weekly_reset_str=weekly_reset_str,
            category=self._category,
            last_poked_at=last_poked_at,
            details={
                "plan_type": rl.get("planType"),
                "credits": rl.get("credits"),
                "primary": primary,
                "secondary": secondary,
            },
        )

    def poke(self, prompt: str = "Hello, how are you doing?", force: bool = False) -> PokeResult:
        status = self.get_status()
        if status.is_active and not force:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="skipped",
                message=f"Codex 5h window already active ({status.time_remaining_str} remaining, {status.used_percent}% used). Skipped poke.",
                time_remaining_str=status.time_remaining_str,
                used_percent=status.used_percent,
                verified_active=True,
            )

        codex_bin = shutil.which("codex") or shutil.which("codex.cmd")
        if not codex_bin:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="error",
                message="Codex CLI (codex) not found in PATH.",
            )

        # Run non-interactive codex exec
        cmd = [codex_bin, "exec", prompt, "--ephemeral", "--skip-git-repo-check", "--color", "never"]
        try:
            res = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
            )
            raw_out = (res.stdout or "").strip() or (res.stderr or "").strip()
            reply = extract_reply_snippet(raw_out)
            now_iso = datetime.now(timezone.utc).isoformat()
            update_agent_state(self.agent_id, {"last_poked_at": now_iso})

            # Verify locally
            time.sleep(1.0)
            new_status = self.get_status()
            if not new_status.is_active:
                time.sleep(1.5)
                new_status = self.get_status()

            if new_status.is_active:
                return PokeResult(
                    agent_id=self.agent_id,
                    agent_name=self.display_name,
                    action_taken="poked",
                    message=f"Verified ACTIVE ({new_status.time_remaining_str} remaining, {new_status.used_percent}% used)",
                    reply=reply,
                    verified_active=True,
                    time_remaining_str=new_status.time_remaining_str,
                    used_percent=new_status.used_percent,
                    details=raw_out[:300],
                )
            else:
                return PokeResult(
                    agent_id=self.agent_id,
                    agent_name=self.display_name,
                    action_taken="unverified",
                    message="Model replied, but 5h window did not register as active",
                    reply=reply,
                    verified_active=False,
                    time_remaining_str="Inactive",
                    used_percent=0.0,
                    details=raw_out[:300],
                )
        except subprocess.TimeoutExpired:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="error",
                message="Timed out after 45s waiting for Codex exec.",
            )
        except Exception as e:
            return PokeResult(
                agent_id=self.agent_id,
                agent_name=self.display_name,
                action_taken="error",
                message=f"Error executing codex poke: {e}",
            )
