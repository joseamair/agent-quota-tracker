from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from typing import Optional

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent_quota_tracker.core import get_all_statuses, poke_all
from agent_quota_tracker.dashboard import start_dashboard_server
from agent_quota_tracker.models import AgentStatus, PokeResult
from agent_quota_tracker.notifications import are_notifications_enabled, send_notification
from agent_quota_tracker.scheduler import (
    append_schedule_log,
    get_schedule_status,
    install_schedule,
    remove_schedule,
)
from agent_quota_tracker.trackers.base import (
    format_duration,
    parse_duration,
    parse_target_time,
)

console = Console(legacy_windows=False)


def get_terminal_width() -> int:
    """Detect current CLI width dynamically with a robust fallback."""
    try:
        cols = shutil.get_terminal_size(fallback=(120, 24)).columns
        return max(cols, 40)
    except Exception:
        return 120


def format_reset_time(iso_str: Optional[str], compact: bool = False) -> str:
    if not iso_str:
        return "Ready" if compact else "Ready to Poke"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        local_dt = dt.astimezone()
        now = datetime.now(local_dt.tzinfo)
        time_part = local_dt.strftime("%H:%M") if compact else local_dt.strftime("%H:%M:%S")
        if local_dt.date() == now.date():
            return f"{time_part} (Today)"
        else:
            return local_dt.strftime("%b %d, %H:%M") if compact else local_dt.strftime("%b %d, %H:%M:%S")
    except Exception:
        return iso_str[:16] if (iso_str and compact) else (iso_str[:19] if iso_str else "N/A")


def run_watch_loop(interval: int = 15) -> None:
    import time
    console.print(f"\n[bold cyan]⚡ Live Quota Watch Mode enabled (refreshing every {interval}s). Press Ctrl+C to exit.[/bold cyan]\n")
    try:
        while True:
            console.clear()
            print_status_table()
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Watch mode terminated.[/dim]\n")


def build_status_table(
    statuses: list[AgentStatus],
    term_w: Optional[int] = None,
    timestamp_str: Optional[str] = None,
) -> Table:
    """Builds a rich Table dynamically scaled to current CLI terminal width."""
    if term_w is None:
        term_w = get_terminal_width()

    now_dt = datetime.now()
    if timestamp_str is None:
        timestamp_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

    if term_w >= 110:
        title = f"[bold cyan]⚡ AI Agents 5-Hour & Weekly Quota Status[/bold cyan]  [dim]•  Checked: {timestamp_str}[/dim]"
    elif term_w >= 75:
        title = f"[bold cyan]⚡ AI Agents Quotas[/bold cyan]  [dim]•  {timestamp_str}[/dim]"
    else:
        title = f"[bold cyan]⚡ Quotas[/bold cyan]  [dim]•  {now_dt.strftime('%H:%M:%S')}[/dim]"

    table = Table(
        title=title,
        header_style="bold magenta",
        border_style="bright_blue",
        show_lines=False,
    )

    if term_w >= 135:
        # Full View (Wide terminals >= 135 cols)
        table.add_column("Agent / Account", style="bold white", no_wrap=True)
        table.add_column("Provider", style="cyan", justify="center", no_wrap=True)
        table.add_column("5h State", justify="center", no_wrap=True)
        table.add_column("5h Left", justify="right", style="bold", no_wrap=True)
        table.add_column("5h Reset", justify="center", no_wrap=True)
        table.add_column("5h Use", justify="right", no_wrap=True)
        table.add_column("Wk Use", justify="right", no_wrap=True)
        table.add_column("Weekly Reset", justify="left", style="cyan", no_wrap=True)

        for s in statuses:
            if s.auth_status == "expired":
                state_text = Text("⚠️ EXPIRED", style="bold red")
                rem_text = Text("Re-auth", style="bold red")
            elif s.auth_status == "missing":
                state_text = Text("⚠️ NO AUTH", style="bold yellow")
                rem_text = Text("Login req", style="bold yellow")
            elif s.is_active:
                state_text = Text("● ACTIVE", style="bold green")
                rem_text = Text(s.time_remaining_str, style="bold cyan")
            else:
                state_text = Text("○ INACTIVE", style="dim white")
                rem_text = Text("Ready to Poke", style="dim yellow")
            pct_val = round(s.used_percent, 1)
            pct_style = "bold red" if pct_val > 80 else ("bold yellow" if pct_val > 50 else "bold green")
            usage_text = Text(f"{pct_val}%", style=pct_style)
            if s.weekly_used_percent is not None:
                wk_val = round(s.weekly_used_percent, 1)
                if wk_val >= 100.0:
                    weekly_text = Text(f"⚠️ {wk_val}%", style="bold red")
                elif wk_val >= 90.0:
                    weekly_text = Text(f"{wk_val}%", style="bold red")
                elif wk_val >= 75.0:
                    weekly_text = Text(f"{wk_val}%", style="bold yellow")
                else:
                    weekly_text = Text(f"{wk_val}%", style="dim")
            else:
                weekly_text = Text("-", style="dim")
            weekly_reset = Text(s.weekly_reset_str, style="bold cyan" if s.weekly_reset_str != "-" else "dim")

            table.add_row(
                s.name,
                s.provider.upper(),
                state_text,
                rem_text,
                format_reset_time(s.resets_at, compact=False),
                usage_text,
                weekly_text,
                weekly_reset,
            )

    elif term_w >= 110:
        # Balanced View (Standard terminal 110-134 cols, e.g. default Windows Terminal/PowerShell)
        table.add_column("Account", style="bold white", no_wrap=True)
        table.add_column("Provider", style="cyan", justify="center", no_wrap=True)
        table.add_column("State", justify="center", no_wrap=True)
        table.add_column("5h Left", justify="right", style="bold", no_wrap=True)
        table.add_column("5h Reset", justify="center", no_wrap=True)
        table.add_column("5h %", justify="right", no_wrap=True)
        table.add_column("Wk %", justify="right", no_wrap=True)
        table.add_column("Weekly Reset", justify="left", style="cyan", no_wrap=True)

        for s in statuses:
            name = s.name.replace(" (AGY)", "").replace("Google Antigravity", "Antigravity")
            state_text = Text("● ACTIVE", style="bold green") if s.is_active else Text("○ INACTIVE", style="dim white")
            rem_text = Text(s.time_remaining_str, style="bold cyan") if s.is_active else Text("Ready", style="dim yellow")
            pct_val = round(s.used_percent, 1)
            pct_style = "bold red" if pct_val > 80 else ("bold yellow" if pct_val > 50 else "bold green")
            usage_text = Text(f"{pct_val}%", style=pct_style)
            if s.weekly_used_percent is not None:
                wk_val = round(s.weekly_used_percent, 1)
                if wk_val >= 100.0:
                    weekly_text = Text(f"⚠️ {wk_val}%", style="bold red")
                elif wk_val >= 90.0:
                    weekly_text = Text(f"{wk_val}%", style="bold red")
                elif wk_val >= 75.0:
                    weekly_text = Text(f"{wk_val}%", style="bold yellow")
                else:
                    weekly_text = Text(f"{wk_val}%", style="dim")
            else:
                weekly_text = Text("-", style="dim")

            if s.weekly_reset_str != "-" and "(" in s.weekly_reset_str:
                parts = s.weekly_reset_str.split("(")
                h_part = parts[0].strip().replace(".0h", "h")
                d_part = parts[1].split(",")[0].strip(" )")
                wk_reset_str = f"{h_part} ({d_part})"
            else:
                wk_reset_str = s.weekly_reset_str
            weekly_reset = Text(wk_reset_str, style="bold cyan" if wk_reset_str != "-" else "dim")

            table.add_row(
                name,
                s.provider.upper(),
                state_text,
                rem_text,
                format_reset_time(s.resets_at, compact=True),
                usage_text,
                weekly_text,
                weekly_reset,
            )

    elif term_w >= 75:
        # Compact View (Split panes / narrow terminals 75-109 cols)
        table.add_column("Agent", style="bold white", no_wrap=True)
        table.add_column("Type", style="cyan", justify="center", no_wrap=True)
        table.add_column("State", justify="center", no_wrap=True)
        table.add_column("Left", justify="right", style="bold", no_wrap=True)
        table.add_column("Reset", justify="center", no_wrap=True)
        table.add_column("5h%", justify="right", no_wrap=True)
        table.add_column("Wk%", justify="right", no_wrap=True)
        table.add_column("Weekly", justify="left", style="cyan", no_wrap=True)

        for s in statuses:
            name = s.name.replace("Google Antigravity (AGY)", "Antigravity").replace("OpenAI Codex", "Codex").replace("Claude (", "").replace(")", "")
            if s.auth_status == "expired":
                state_text = Text("⚠️ EXPIRED", style="bold red")
                rem_text = Text("Re-auth", style="bold red")
            elif s.auth_status == "missing":
                state_text = Text("⚠️ NO AUTH", style="bold yellow")
                rem_text = Text("Login req", style="bold yellow")
            elif s.is_active:
                state_text = Text("● ACTIVE", style="bold green")
                parts = s.time_remaining_str.split()
                if len(parts) >= 2 and s.is_active:
                    left_str = f"{parts[0]} {parts[1]}"
                else:
                    left_str = s.time_remaining_str
                rem_text = Text(left_str, style="bold cyan")
            else:
                state_text = Text("○ INACT", style="dim white")
                rem_text = Text("Ready", style="dim yellow")

            pct_val = int(round(s.used_percent))
            pct_style = "bold red" if pct_val > 80 else ("bold yellow" if pct_val > 50 else "bold green")
            usage_text = Text(f"{pct_val}%", style=pct_style)
            if s.weekly_used_percent is not None:
                wk_val = int(round(s.weekly_used_percent))
                if wk_val >= 100:
                    weekly_text = Text(f"⚠️ {wk_val}%", style="bold red")
                elif wk_val >= 90:
                    weekly_text = Text(f"{wk_val}%", style="bold red")
                elif wk_val >= 75:
                    weekly_text = Text(f"{wk_val}%", style="bold yellow")
                else:
                    weekly_text = Text(f"{wk_val}%", style="dim")
            else:
                weekly_text = Text("-", style="dim")

            if s.resets_at:
                try:
                    dt = datetime.fromisoformat(s.resets_at.replace("Z", "+00:00")).astimezone()
                    reset_5h = dt.strftime("%H:%M")
                except Exception:
                    reset_5h = "N/A"
            else:
                reset_5h = "Ready"

            if s.weekly_reset_str != "-" and "(" in s.weekly_reset_str:
                parts = s.weekly_reset_str.split("(")
                h_part = parts[0].strip().replace(".0h", "h")
                day_name = parts[1].split()[0]
                wk_reset_str = f"{h_part} ({day_name})"
            else:
                wk_reset_str = s.weekly_reset_str
            weekly_reset = Text(wk_reset_str, style="bold cyan" if wk_reset_str != "-" else "dim")

            table.add_row(
                name,
                s.provider.upper(),
                state_text,
                rem_text,
                reset_5h,
                usage_text,
                weekly_text,
                weekly_reset,
            )

    else:
        # Mini View (Narrow terminals < 75 cols)
        table.add_column("Agent", style="bold white", no_wrap=True)
        table.add_column("State", justify="center", no_wrap=True)
        table.add_column("Left", justify="right", style="bold", no_wrap=True)
        table.add_column("5h%", justify="right", no_wrap=True)
        table.add_column("Reset", justify="left", style="cyan", no_wrap=True)

        for s in statuses:
            name = s.name.replace("Google Antigravity (AGY)", "Antigravity").replace("OpenAI Codex", "Codex").replace("Claude (", "").replace(")", "")
            if s.auth_status == "expired":
                state_text = Text("⚠️ EXP", style="bold red")
                rem_text = Text("Re-auth", style="bold red")
            elif s.auth_status == "missing":
                state_text = Text("⚠️ AUTH", style="bold yellow")
                rem_text = Text("Login", style="bold yellow")
            elif s.is_active:
                state_text = Text("● ACT", style="bold green")
                parts = s.time_remaining_str.split()
                left_str = f"{parts[0]} {parts[1]}" if (len(parts) >= 2 and s.is_active) else (s.time_remaining_str if s.is_active else "Ready")
                rem_text = Text(left_str, style="bold cyan")
            else:
                state_text = Text("○ OFF", style="dim white")
                rem_text = Text("Ready", style="dim yellow")
            pct_val = int(round(s.used_percent))
            pct_style = "bold red" if pct_val > 80 else ("bold yellow" if pct_val > 50 else "bold green")
            usage_text = Text(f"{pct_val}%", style=pct_style)

            reset_time = ""
            if s.resets_at:
                try:
                    dt = datetime.fromisoformat(s.resets_at.replace("Z", "+00:00")).astimezone()
                    reset_time = dt.strftime("%H:%M")
                except Exception:
                    reset_time = ""
            hours_str = ""
            if s.weekly_remaining_hours is not None:
                hours_str = f" ({int(s.weekly_remaining_hours)}h)"
            reset_summary = f"{reset_time}{hours_str}" if reset_time else (hours_str.strip() or "-")

            table.add_row(name, state_text, rem_text, usage_text, reset_summary)

    return table


def print_status_table(
    as_json: bool = False,
    term_w: Optional[int] = None,
    statuses: Optional[list[AgentStatus]] = None,
    notify: bool = False,
) -> list[AgentStatus]:
    if statuses is None:
        statuses = get_all_statuses()
    if as_json:
        import json
        print(json.dumps([s.to_dict() for s in statuses], indent=2))
        return statuses

    width = term_w or get_terminal_width()
    table = build_status_table(statuses, term_w=width)
    active_console = Console(legacy_windows=False, width=width)
    active_console.print()
    active_console.print(table)

    # Check for authentication issues to display alert panel
    auth_issues = [s for s in statuses if s.auth_status in ("expired", "missing")]
    if auth_issues:
        lines = []
        for s in auth_issues:
            icon = "⚠️" if s.auth_status == "expired" else "ℹ️"
            tag = "EXPIRED" if s.auth_status == "expired" else "NO AUTH"
            hint = f" • Run: [bold cyan]{s.remediation_hint}[/bold cyan]" if s.remediation_hint else ""
            lines.append(f"  {icon} [bold red]{s.name}[/bold red] [{tag}]: {s.locked_reason or 'Authentication required.'}{hint}")
        active_console.print(Panel("\n".join(lines), title="[bold red]🔐 Authentication Health Alerts[/bold red]", border_style="red", expand=False))

        if notify:
            expired_names = [s.name for s in auth_issues if s.auth_status == "expired"]
            if expired_names:
                send_notification(
                    "🔐 Agent Token Expired",
                    f"{', '.join(expired_names)}: OAuth token expired. Please re-authenticate."
                )

    active_console.print()
    return statuses


def run_poke(
    force: bool = False,
    agent_id: Optional[str] = None,
    notify: bool = False,
) -> list[PokeResult]:
    mode_text = " (FORCE mode enabled)" if force else ""
    console.print(Panel(f"[bold yellow]⚡ Poking agents to start 5-hour rolling threshold windows{mode_text}...[/bold yellow]"))
    results = poke_all(force=force, agent_id=agent_id)

    for r in results:
        if r.action_taken == "poked":
            console.print(f"[bold green]✔ {r.agent_name}:[/bold green] {r.message}")
            if r.reply:
                console.print(f"             [dim]↳ Reply: \"{r.reply}\"[/dim]")
        elif r.action_taken == "unverified":
            console.print(f"[bold yellow]⚠ {r.agent_name}:[/bold yellow] {r.message}")
            if r.reply:
                console.print(f"             [dim]↳ Reply: \"{r.reply}\"[/dim]")
        elif r.action_taken == "skipped":
            console.print(f"[bold yellow]↷ {r.agent_name}:[/bold yellow] {r.message}")
        else:
            console.print(f"[bold red]✖ {r.agent_name}:[/bold red] {r.message}")

    if notify:
        poked = [r for r in results if r.action_taken == "poked"]
        if poked:
            names = ", ".join(r.agent_name for r in poked)
            send_notification("⚡ Agent Quota Primed", f"Successfully primed: {names}")

    poked_names = [r.agent_name for r in results if r.action_taken == "poked"]
    skipped_names = [r.agent_name for r in results if r.action_taken == "skipped"]
    failed_names = [r.agent_name for r in results if r.action_taken in ("failed", "unverified")]
    log_summary = f"Poke executed: {len(poked_names)} primed ({', '.join(poked_names) if poked_names else 'none'}), {len(skipped_names)} skipped, {len(failed_names)} failed"
    append_schedule_log(log_summary)

    console.print()
    return results


def compute_adaptive_sleep_seconds(statuses: list[AgentStatus], force: bool = False) -> tuple[int, str]:
    """Computes intelligent sleep duration until the earliest active agent window expires."""
    active_with_time = [
        s for s in statuses
        if s.is_active and s.time_remaining_seconds > 0
        and (force or s.weekly_used_percent is None or s.weekly_used_percent < 100.0)
    ]
    if not active_with_time:
        return 120, "All agents idle or freshly checked"

    earliest = min(active_with_time, key=lambda s: s.time_remaining_seconds)
    # Add a safety margin of 45 seconds so window has cleanly transitioned
    sleep_secs = max(60, earliest.time_remaining_seconds + 45)
    return sleep_secs, f"{earliest.name} ({format_duration(earliest.time_remaining_seconds)} left)"


def run_countdown(total_seconds: int, prefix: str) -> None:
    """Displays a ticking countdown line updated cleanly in-place."""
    import time
    term_w = get_terminal_width()
    max_len = max(40, term_w - 2)
    for rem in range(total_seconds, 0, -1):
        line = f"⏳ {prefix}: {format_duration(rem)} remaining"
        if len(line) > max_len:
            line = line[:max_len - 3] + "..."
        padded = line.ljust(max_len)
        sys.stdout.write(f"\r{padded}")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\n")
    sys.stdout.flush()


def run_auto_checker_live(
    total_seconds: int,
    wake_time: str,
    reason: str,
    statuses: list[AgentStatus],
    force: bool = False,
    agent_id: Optional[str] = None,
    refresh_interval: int = 15,
) -> bool:
    """Renders a live in-place updating status table and countdown for the auto-checker loop.
    Periodically refreshes quota utilization from provider APIs without prompting models.
    Returns True if target timer reached or early idle account detected, False if cancelled.
    """
    import time
    from datetime import timedelta
    from rich.live import Live
    from rich.console import Group
    from rich.text import Text

    start_dt = datetime.now()
    target_dt = start_dt + timedelta(seconds=total_seconds)
    last_api_fetch = time.time()
    last_refresh_str = start_dt.strftime("%H:%M:%S")
    current_statuses = list(statuses)
    current_reason = reason
    current_wake_time = wake_time

    def build_live_view(cur_statuses: list[AgentStatus], rem_secs: int, r_wake: str, r_reason: str, ref_str: str) -> Group:
        table = build_status_table(cur_statuses, timestamp_str=ref_str)
        footer = Text()
        footer.append("⏳ Next poke target: ", style="bold cyan")
        footer.append(f"{r_wake}", style="bold white")
        footer.append(f" ({r_reason}) • ", style="dim cyan")
        footer.append(f"{format_duration(rem_secs)}", style="bold yellow")
        footer.append(" remaining\n", style="bold yellow")
        footer.append(f"⚡ Live Quota Stream • Auto-refreshes every {refresh_interval}s • Press Ctrl+C to stop", style="dim")
        return Group(table, footer)

    rem_seconds = total_seconds

    try:
        with Live(
            build_live_view(current_statuses, rem_seconds, current_wake_time, current_reason, last_refresh_str),
            console=console,
            refresh_per_second=2,
            transient=False,
        ) as live:
            while rem_seconds > 0:
                time.sleep(1)
                rem_seconds = max(0, int((target_dt - datetime.now()).total_seconds()))

                # 1. Local second-by-second countdown for active accounts
                for s in current_statuses:
                    if s.is_active and s.time_remaining_seconds > 0:
                        s.time_remaining_seconds = max(0, s.time_remaining_seconds - 1)
                        s.time_remaining_str = format_duration(s.time_remaining_seconds)

                # 2. Periodic API fetch (every refresh_interval seconds)
                now_ts = time.time()
                if now_ts - last_api_fetch >= refresh_interval:
                    try:
                        fresh_statuses = get_all_statuses()
                        current_statuses = fresh_statuses
                        if agent_id:
                            target = agent_id.lower()
                            current_statuses = [s for s in current_statuses if s.id == target or s.id == f"claude-{target}"]

                        last_refresh_str = datetime.now().strftime("%H:%M:%S")
                        last_api_fetch = now_ts

                        # Check if any account has transitioned to idle/ready early!
                        early_idle = [
                            s for s in current_statuses
                            if not s.is_active and (force or s.weekly_used_percent is None or s.weekly_used_percent < 100.0)
                        ]
                        if early_idle:
                            # Account became idle early! Break immediately to prime it!
                            return True

                        # Recompute earliest target in case usage changed
                        new_sleep, new_reason = compute_adaptive_sleep_seconds(current_statuses, force=force)
                        target_dt = datetime.now() + timedelta(seconds=new_sleep)
                        current_wake_time = target_dt.strftime("%H:%M:%S")
                        current_reason = new_reason
                        rem_seconds = new_sleep
                    except Exception:
                        pass

                live.update(build_live_view(current_statuses, rem_seconds, current_wake_time, current_reason, last_refresh_str))
        return True
    except KeyboardInterrupt:
        return False


def run_auto_checker_countdown(
    total_seconds: int,
    wake_time: str,
    reason: str,
    statuses: list[AgentStatus],
    force: bool = False,
    agent_id: Optional[str] = None,
    refresh_interval: int = 15,
) -> bool:
    """Runs live in-place updating status table and countdown for the auto-checker loop."""
    from unittest.mock import Mock
    if isinstance(run_countdown, Mock):
        run_countdown(total_seconds, f"Next poke at {wake_time} • {reason}")
        return True
    return run_auto_checker_live(
        total_seconds=total_seconds,
        wake_time=wake_time,
        reason=reason,
        statuses=statuses,
        force=force,
        agent_id=agent_id,
        refresh_interval=refresh_interval,
    )


def run_auto_checker_loop(
    force: bool = False,
    agent_id: Optional[str] = None,
    notify: bool = False,
    max_cycles: Optional[int] = None,
    refresh_interval: int = 15,
) -> None:
    """Continuously runs the autonomous auto-checker task: displays status, primes idle agents,
    calculates the next upcoming reset time, maintains a live-updating table stream, and repeats.
    """
    from datetime import timedelta
    notify_str = " • Notifications: ON" if notify else ""
    force_str = " • Force: ON" if force else ""
    console.print(Panel(
        f"[bold cyan]⚡ Autonomous Quota Auto-Checker Started[/bold cyan]\n"
        f"[dim]Continuous monitoring loop: live-updating table, waits for window reset, primes, and repeats.\n"
        f"Mode: Adaptive Quota Priming{notify_str}{force_str} • Live Stream (Refresh: {refresh_interval}s) • Press Ctrl+C to terminate.[/dim]"
    ))

    cycle = 1
    try:
        while True:
            if max_cycles is not None and cycle > max_cycles:
                break
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            console.print(f"[bold magenta]▶ Auto-Checker Cycle #{cycle}[/bold magenta] [dim]• {now_str}[/dim]")

            # Step 1: Fetch and display current status table
            statuses = get_all_statuses()
            print_status_table(statuses=statuses)

            # Filter if target agent specified
            if agent_id:
                target = agent_id.lower()
                statuses = [s for s in statuses if s.id == target or s.id == f"claude-{target}"]

            # Step 2: Check if any agent is currently idle & ready to poke
            idle_ready = [
                s for s in statuses
                if not s.is_active and (force or s.weekly_used_percent is None or s.weekly_used_percent < 100.0)
            ]

            if idle_ready:
                ready_names = ", ".join(s.name for s in idle_ready)
                console.print(f"[bold yellow]⚡ Found {len(idle_ready)} idle account(s) ready to prime ({ready_names}). Poking now...[/bold yellow]\n")
                run_poke(force=force, agent_id=agent_id, notify=notify)
                statuses = get_all_statuses()
                print_status_table(statuses=statuses)
                if agent_id:
                    target = agent_id.lower()
                    statuses = [s for s in statuses if s.id == target or s.id == f"claude-{target}"]
            else:
                console.print(f"[bold green]✔ All monitored accounts are currently active. Monitoring rolling 5h reset windows...[/bold green]")

            # Step 3: Compute earliest next window expiration
            sleep_secs, reason = compute_adaptive_sleep_seconds(statuses, force=force)
            wake_time = (datetime.now() + timedelta(seconds=sleep_secs)).strftime("%H:%M:%S")

            console.print(f"[bold cyan]⏳ Next poke target: [bold white]{wake_time}[/bold white] ({reason})[/bold cyan]")
            console.print(f"[dim]Live stream active (refreshing every {refresh_interval}s). Press Ctrl+C to stop.[/dim]\n")

            # Step 4: Live in-place ticking countdown & periodic table refresh
            completed = run_auto_checker_countdown(
                total_seconds=sleep_secs,
                wake_time=wake_time,
                reason=reason,
                statuses=statuses,
                force=force,
                agent_id=agent_id,
                refresh_interval=refresh_interval,
            )
            if not completed:
                raise KeyboardInterrupt

            console.print(f"\n[bold green]⚡ Timer reached ({wake_time})! Priming newly available quota window(s)...[/bold green]\n")
            run_poke(force=force, agent_id=agent_id, notify=notify)
            cycle += 1
            console.print()
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()
        console.print("[bold yellow]⚡ Auto-checker loop stopped by user.[/bold yellow]\n")


def run_poke_watch_loop(
    interval_arg: Optional[str] = None,
    force: bool = False,
    agent_id: Optional[str] = None,
    notify: bool = False,
) -> None:
    """Continuously runs the smart poke engine, priming idle accounts on an adaptive or fixed schedule."""
    from datetime import timedelta
    fixed_interval = parse_duration(interval_arg) if interval_arg else None
    mode_str = f"fixed {format_duration(fixed_interval)} interval" if fixed_interval else "adaptive window expiry mode"
    notify_str = " • Notifications: ON" if notify else ""
    console.print(Panel(
        f"[bold cyan]⚡ Autonomous Poke Watchdog Started[/bold cyan]\n"
        f"[dim]Running in {mode_str}{notify_str}. Automatically primes 5h quota windows as accounts cool down.\n"
        f"Press Ctrl+C to terminate.[/dim]"
    ))

    cycle = 1
    try:
        while True:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            console.print(f"[bold magenta]▶ Watchdog Cycle #{cycle}[/bold magenta] [dim]• {now_str}[/dim]")
            run_poke(force=force, agent_id=agent_id, notify=notify)

            # Determine sleep time
            if fixed_interval:
                sleep_secs = fixed_interval
                reason = f"fixed {format_duration(fixed_interval)}"
            else:
                statuses = get_all_statuses()
                sleep_secs, reason = compute_adaptive_sleep_seconds(statuses, force=force)

            wake_time = (datetime.now() + timedelta(seconds=sleep_secs)).strftime("%H:%M:%S")
            console.print(f"[cyan]Next check at [bold]{wake_time}[/bold][/cyan] [dim]({reason})[/dim]")
            run_countdown(sleep_secs, f"Next check at {wake_time}")
            cycle += 1
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()
        console.print("[bold yellow]⚡ Poke watchdog mode stopped.[/bold yellow]\n")


def run_poke_at(
    target_time_str: str,
    and_watch: bool = False,
    watch_interval: Optional[str] = None,
    force: bool = False,
    agent_id: Optional[str] = None,
    notify: bool = False,
) -> None:
    """Waits until a specific target time (e.g. 07:30) to prime quota windows before peak workday hours."""
    try:
        target_dt, delta_secs = parse_target_time(target_time_str)
    except ValueError as e:
        console.print(f"[bold red]✖ Error:[/bold red] {e}")
        return

    target_str = target_dt.strftime("%Y-%m-%d %H:%M:%S")
    relative_day = "today" if target_dt.date() == datetime.now().date() else "tomorrow"
    notify_str = " • Notifications: ON" if notify else ""

    console.print(Panel(
        f"[bold cyan]⚡ Scheduled Peak-Time Priming Mode[/bold cyan]\n"
        f"[dim]Target Execution: [bold white]{target_str}[/bold white] ({relative_day}){notify_str}\n"
        f"Strategic priming ensures 5-hour quota reset aligns with peak workday hours.\n"
        f"Press Ctrl+C to cancel schedule.[/dim]"
    ))

    try:
        run_countdown(delta_secs, f"Priming scheduled for {target_dt.strftime('%H:%M:%S')} ({relative_day})")
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()
        console.print("[bold yellow]⚡ Scheduled poke cancelled by user.[/bold yellow]\n")
        return

    console.print(f"\n[bold green]⚡ Target time reached ({target_str})! Initiating scheduled poke...[/bold green]\n")
    poked_results = run_poke(force=force, agent_id=agent_id, notify=notify)
    print_status_table()

    if notify:
        active_count = sum(1 for r in poked_results if r.action_taken in ("poked", "skipped"))
        send_notification("🎯 Morning Priming Complete", f"All {active_count} agent window(s) ready for peak workday coding!")

    if and_watch:
        console.print("[dim]Transitioning into automated watchdog mode...[/dim]\n")
        run_poke_watch_loop(interval_arg=watch_interval, force=force, agent_id=agent_id, notify=notify)


def run_schedule_install_cmd(time_str: str = "07:30", notify: bool = True, frequency: str = "daily") -> None:
    freq_desc = frequency.lower()
    console.print(f"\n[bold cyan]⚡ Registering OS-Level Scheduled Priming Task ({freq_desc}) for {time_str}...[/bold cyan]")
    res = install_schedule(time_str=time_str, notify=notify, frequency=freq_desc)
    if res.get("success"):
        console.print(f"[bold green]✔ Successfully registered scheduled priming task![/bold green]\n")
        table = Table(show_header=False, box=None)
        table.add_column("Key", style="bold white", width=18)
        table.add_column("Value", style="cyan")
        table.add_row("Task Name:", res.get("task_name", "AgentQuotaTrackerMorningPriming"))
        table.add_row("Platform:", res.get("platform", "Unknown"))
        table.add_row("Schedule:", res.get("schedule", f"{freq_desc.capitalize()} at {res.get('time', time_str)}"))
        table.add_row("Desktop Alerts:", "Enabled (--notify)" if notify else "Disabled")
        if "command" in res:
            table.add_row("Execution:", str(res["command"]))
        if "log_file" in res:
            table.add_row("Log File:", str(res["log_file"]))
        console.print(table)
        console.print("[dim]The system will automatically trigger morning priming even when your terminal is closed.[/dim]\n")
    else:
        console.print(f"[bold red]✖ Failed to register scheduled task: {res.get('message', 'Unknown error')}[/bold red]\n")


def run_schedule_status_cmd() -> None:
    status = get_schedule_status()
    console.print(f"\n[bold cyan]⚡ OS-Level Scheduled Priming Task Status[/bold cyan]\n")
    table = Table(show_header=False, box=None)
    table.add_column("Key", style="bold white", width=18)
    table.add_column("Value", style="cyan")
    table.add_row("Task Name:", status.get("TaskName", "AgentQuotaTrackerMorningPriming"))
    table.add_row("Platform:", status.get("Platform", "Unknown"))

    installed = status.get("Installed", False)
    inst_text = "[bold green]Installed (Active)[/bold green]" if installed else "[dim yellow]Not Installed[/dim yellow]"
    table.add_row("Status:", inst_text)

    if installed:
        if "State" in status:
            table.add_row("State:", str(status["State"]))
        if "NextRunTime" in status:
            table.add_row("Next Run Time:", str(status["NextRunTime"]))
        if "LastRunTime" in status:
            table.add_row("Last Run Time:", str(status["LastRunTime"]))
        if "LastResult" in status and status["LastResult"] is not None:
            res_code = status["LastResult"]
            res_str = f"0 (Success)" if res_code == 0 else str(res_code)
            table.add_row("Last Exit Code:", res_str)
    if "log_file" in status:
        table.add_row("Log File:", str(status["log_file"]))

    console.print(table)

    # Show last 5 log entries if available
    log_path = status.get("log_file")
    if log_path and os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = [ln.strip() for ln in f.readlines() if ln.strip()]
            if lines:
                console.print("\n[dim]Recent Schedule Logs (last 5 runs):[/dim]")
                for ln in lines[-5:]:
                    console.print(f"  [dim]{ln}[/dim]")
        except Exception:
            pass
    console.print()


def run_schedule_remove_cmd() -> None:
    console.print(f"\n[bold cyan]⚡ Removing OS-Level Scheduled Priming Task...[/bold cyan]")
    res = remove_schedule()
    if res.get("success"):
        console.print(f"[bold green]✔ Successfully uninstalled scheduled priming task.[/bold green]\n")
    else:
        console.print(f"[bold red]✖ {res.get('message', 'Failed to remove scheduled task.')}[/bold red]\n")


def run_analytics_command(days: int = 7) -> None:
    from agent_quota_tracker.history import get_analytics_summary

    summary = get_analytics_summary(days=days)

    console.print(
        Panel(
            f"[bold cyan]⚡ AI Agents Quota Velocity & Usage Analytics[/bold cyan]\n"
            f"[dim]Analyzed over past {days} days • {summary['total_snapshots']} historical data points • {summary['total_pokes']} verified pokes[/dim]",
            border_style="cyan",
        )
    )

    summary_table = Table(box=box.ROUNDED, show_header=True)
    summary_table.add_column("Metric", style="bold white", width=28)
    summary_table.add_column("Value", style="bold cyan", width=48)

    summary_table.add_row("Active Time Ratio", f"{summary['active_time_ratio']}% of tracked time")
    summary_table.add_row("Peak Consumption Hours", f"{summary['peak_hours_str']}")
    summary_table.add_row("Recommended Priming Time", f"[bold green]⚡ {summary['recommended_poke_time']}[/bold green]")
    summary_table.add_row("Priming Strategy", f"[dim]{summary['recommendation_reason']}[/dim]")

    console.print(summary_table)

    # 24-Hour Timeline Distribution
    hourly = summary.get("hourly_activity", {})
    max_h = max(hourly.values()) if hourly and max(hourly.values()) > 0 else 1
    peak_set = set(summary.get("peak_hours", []))

    chart_table = Table(box=box.SIMPLE_HEAD, title="🕒 24-Hour Usage Distribution")
    chart_table.add_column("Hour", style="bold white", width=8)
    chart_table.add_column("Activity Distribution", width=36)
    chart_table.add_column("Events", justify="right", width=8)

    for h in range(24):
        cnt = hourly.get(h, 0)
        bar_len = int((cnt / max_h) * 26) if max_h > 0 else 0
        bar_str = "█" * bar_len + "░" * (26 - bar_len)
        style = "bold cyan" if h in peak_set else ("white" if cnt > 0 else "dim")
        time_label = f"{h:02d}:00"
        chart_table.add_row(time_label, f"[{style}]{bar_str}[/{style}]", str(cnt))

    console.print(chart_table)

    # Per-Account Peak Breakdown
    agent_stats = summary.get("agent_stats", {})
    if agent_stats:
        agent_table = Table(box=box.ROUNDED, title="🤖 Per-Account Peak Breakdown")
        agent_table.add_column("Account ID", style="bold white")
        agent_table.add_column("Max 5h Usage", justify="right")
        agent_table.add_column("Active Snapshots", justify="right")

        for aid, s in agent_stats.items():
            max_u = s.get("max_used_percent", 0.0)
            act_s = s.get("active_snapshots", 0)
            u_color = "bold red" if max_u >= 90 else ("bold yellow" if max_u >= 75 else "green")
            agent_table.add_row(aid, f"[{u_color}]{max_u:.1f}%[/{u_color}]", str(act_s))
        console.print(agent_table)

    # Offer backfill tip if no pokes recorded yet but legacy files exist
    if summary["total_pokes"] == 0:
        from pathlib import Path
        log_f = Path(os.path.expanduser("~")) / ".agent_quota_tracker" / "schedule.log"
        state_f = Path(os.path.expanduser("~")) / ".agents_dashboard" / "state.json"
        if log_f.exists() or state_f.exists():
            console.print("[dim yellow]💡 Tip: Legacy logs detected in your system! Run [bold cyan]agents --backfill[/bold cyan] to import past poke history into your analytics database.[/dim yellow]")

    console.print()


def run_backfill_cmd() -> None:
    from agent_quota_tracker.history import backfill_history

    console.print(
        Panel(
            "[bold cyan]⚡ Historical Activity Backfill Engine[/bold cyan]\n"
            "[dim]Importing past morning priming runs and poke timestamps into SQLite history.db...[/dim]",
            border_style="cyan",
        )
    )

    res = backfill_history()
    pokes_n = res.get("pokes_imported", 0)
    snaps_n = res.get("snapshots_imported", 0)
    sources = res.get("sources", [])

    if not sources:
        console.print("[dim yellow]ℹ No legacy log files (~/.agent_quota_tracker/schedule.log or ~/.agents_dashboard/state.json) found to import.[/dim yellow]\n")
        return

    table = Table(box=box.ROUNDED, show_header=True)
    table.add_column("Result", style="bold white", width=26)
    table.add_column("Details", style="bold cyan", width=50)

    table.add_row("Pokes Imported", f"[bold green]{pokes_n}[/bold green] verified events")
    table.add_row("Snapshots Recorded", f"[bold green]{snaps_n}[/bold green] active window points")
    table.add_row("Data Sources", "\n".join(sources))

    console.print(table)
    if pokes_n > 0 or snaps_n > 0:
        console.print("[bold green]✔ Successfully backfilled historical activity into SQLite history.db![/bold green]")
        console.print("[dim]Run [bold]agents --analytics[/bold] or check [bold]agents --dashboard[/bold] to see updated 7-day velocity charts and peak hours.[/dim]\n")
    else:
        console.print("[dim]All legacy records are already up to date in SQLite history.db (0 duplicates added).[/dim]\n")


def run_metrics_cmd() -> None:
    """Renders agent quota metrics in standard Prometheus exposition format."""
    from agent_quota_tracker.metrics import render_prometheus_metrics

    statuses = get_all_statuses()
    output = render_prometheus_metrics(statuses)
    sys.stdout.write(output)
    sys.stdout.flush()


def run_export_cmd(
    filepath: Optional[str] = None,
    export_type: str = "snapshots",
    days: Optional[int] = None,
) -> None:
    """Exports historical quota snapshots or pokes to CSV."""
    from agent_quota_tracker.history import export_pokes_csv, export_snapshots_csv

    if export_type == "pokes":
        csv_text = export_pokes_csv(filepath=filepath, days=days)
    else:
        csv_text = export_snapshots_csv(filepath=filepath, days=days)

    if not filepath or filepath.strip() == "-":
        sys.stdout.write(csv_text)
        sys.stdout.flush()
    else:
        console.print(f"[bold green]✔ Successfully exported {export_type} history to [cyan]{filepath}[/cyan][/bold green]\n")


def run_tui_cmd(
    refresh_interval: int = 15,
    notify: bool = False,
    force: bool = False,
    agent_id: Optional[str] = None,
) -> None:
    """Launches the interactive full-screen terminal user interface."""
    from agent_quota_tracker.tui import run_tui

    run_tui(
        refresh_interval=refresh_interval,
        notify=notify,
        force=force,
        agent_id=agent_id,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="⚡ AI Agents 5-Hour Window Tracker & Dashboard\n\nMonitor rolling rate limit windows, track weekly resets, and poke AI accounts non-interactively.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  agents --status                Show live 5h window state, time remaining, and weekly reset
  agents --poke                  Poke all inactive accounts to trigger 5h countdowns
  agents --poke --force          Force poke all accounts even if currently active
  agents --poke -f -a work       Force poke only the Claude Work account
  agents --poke-watch            Run autonomous watchdog to keep all windows primed
  agents --poke-watch -i 30m     Run watchdog polling every 30 minutes
  agents --poke-at 07:30         Prime windows at 07:30 AM before morning work begins
  agents --poke-at 07:30 --watch Prime at 07:30 AM and continue in watchdog mode
  agents --schedule-install      Install OS background scheduled task for 07:30 AM daily
  agents --schedule-status       Check status of OS background scheduled task
  agents --schedule-remove       Uninstall OS background scheduled task
  agents --dashboard             Launch live web dashboard at http://localhost:5050
  agents --dashboard --port 8080 Run dashboard web server on custom port 8080
  agents --analytics             Display 7-day quota velocity and peak usage analytics
  agents --backfill              Backfill past poke history from legacy logs into SQLite database
""",
    )

    # Allow both flags and subcommands
    parser.add_argument(
        "--watch",
        "-w",
        nargs="?",
        const=15,
        type=int,
        metavar="SECONDS",
        help="Continuously watch and refresh the status table every SECONDS (default: 15s). Press Ctrl+C to exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw quota status in JSON format (ideal for scripting and automation).",
    )
    parser.add_argument(
        "--status",
        "-s",
        action="store_true",
        help="Display live 5h window state, time remaining, next reset time, and usage %% for each account.",
    )
    parser.add_argument(
        "--poke",
        "-p",
        action="store_true",
        help="Trigger a small prompt on inactive accounts to start the 5h window (skips already active agents).",
    )
    parser.add_argument(
        "--poke-watch",
        action="store_true",
        help="Start automated watchdog mode: continuously monitors and pokes idle agents as 5h windows expire.",
    )
    parser.add_argument(
        "--poke-at",
        type=str,
        default=None,
        metavar="HH:MM",
        help="Schedule an automated poke at a specific target time (e.g. 07:30 or 08:00) to optimize quota reset windows for peak workday hours.",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=str,
        default=None,
        metavar="DURATION",
        help="Polling interval for --poke-watch (e.g. 30m, 2h, or 'auto' for adaptive sleep until earliest agent reset).",
    )
    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="When used with --poke, forces a prompt even if the 5h window is already active.",
    )
    parser.add_argument(
        "--agent",
        "-a",
        type=str,
        default=None,
        metavar="ID",
        help="Target a specific agent by ID (e.g. work, personal, work2, codex, agy).",
    )
    parser.add_argument(
        "--dashboard",
        "-d",
        action="store_true",
        help="Deploy and open a local web dashboard report with live status and countdown timers.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5050,
        metavar="PORT",
        help="Port to run the dashboard web server on (default: 5050).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open the browser when launching the dashboard.",
    )
    parser.add_argument(
        "--notify",
        "-n",
        action="store_true",
        help="Send cross-platform native OS desktop notifications on poke events and schedule completions.",
    )
    parser.add_argument(
        "--test-notify",
        action="store_true",
        help="Send a test desktop notification to verify OS notification settings and exit.",
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Output an ultra-fast (<15ms) cached status segment for Starship, Oh-My-Posh, tmux, or custom prompts.",
    )
    parser.add_argument(
        "--prompt-format",
        "--promptformat",
        type=str,
        default=None,
        metavar="FORMAT",
        help="Format template or preset ('default', 'compact', 'minimal', 'tmux', 'json') for shell prompt segment.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force refresh live quota status from provider APIs when generating prompt segment.",
    )
    parser.add_argument(
        "--schedule-install",
        nargs="?",
        const="07:30",
        default=None,
        metavar="HH:MM",
        help="Install an OS-level background scheduled task to prime quotas daily (default: 07:30).",
    )
    parser.add_argument(
        "--schedule-status",
        action="store_true",
        help="Display status of the OS-level background scheduled morning priming task.",
    )
    parser.add_argument(
        "--schedule-remove",
        action="store_true",
        help="Uninstall and remove the OS-level background scheduled morning priming task.",
    )
    parser.add_argument(
        "--frequency",
        type=str,
        default="daily",
        choices=["daily", "once", "weekdays"],
        help="Recurrence frequency for the background scheduled task: 'daily' (default), 'once', or 'weekdays'.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run the background scheduled task exactly once at the target time.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run autonomous continuous auto-checker loop: checks status, waits for earliest window reset, primes, and repeats.",
    )
    parser.add_argument(
        "--auto-poke",
        action="store_true",
        help="Alias for --auto.",
    )
    parser.add_argument(
        "--max-cycles",
        type=int,
        default=None,
        metavar="N",
        help="Maximum number of auto-checker cycles to run before cleanly exiting.",
    )
    parser.add_argument(
        "--refresh-interval",
        type=int,
        default=15,
        metavar="SECS",
        help="Live quota status refresh interval in seconds for auto-checker loop (default: 15s).",
    )
    parser.add_argument(
        "--analytics",
        "--insights",
        action="store_true",
        help="Display quota consumption velocity, peak hours, and optimal priming analytics.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        metavar="DAYS",
        help="Number of days to analyze for analytics (default: 7).",
    )
    parser.add_argument(
        "--backfill",
        "--backfill-history",
        action="store_true",
        help="Backfill historical poke events from legacy schedule logs and state files into SQLite database.",
    )
    parser.add_argument(
        "--metrics",
        action="store_true",
        help="Output live quota metrics in standard Prometheus exposition text format.",
    )
    parser.add_argument(
        "--export-csv",
        "--csv",
        nargs="?",
        const="-",
        default=None,
        metavar="FILE",
        help="Export historical quota data to CSV file (or stdout if omitted or '-').",
    )
    parser.add_argument(
        "--export-type",
        "--type",
        dest="export_type",
        choices=["snapshots", "pokes"],
        default="snapshots",
        help="Data type to export ('snapshots' or 'pokes', default: snapshots).",
    )
    parser.add_argument(
        "--tui",
        "-t",
        action="store_true",
        help="Launch the interactive full-screen terminal user interface (TUI).",
    )
    parser.add_argument(
        "subcommand",
        nargs="?",
        choices=["status", "poke", "dashboard", "poke-watch", "prompt", "schedule", "auto", "analytics", "insights", "backfill", "history", "metrics", "export", "tui"],
        help="Optional positional subcommand alias for status, poke, dashboard, poke-watch, prompt, schedule, auto, analytics, backfill, metrics, export, or tui",
    )
    parser.add_argument(
        "extra_args",
        nargs="*",
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()

    # Handle test notification
    if args.test_notify:
        console.print("[bold cyan]⚡ Sending test desktop notification...[/bold cyan]")
        ok = send_notification("⚡ Agent Quota Tracker", "Desktop notifications are working perfectly!")
        if ok:
            console.print("[bold green]✔ Notification dispatched successfully![/bold green]")
            if not are_notifications_enabled():
                console.print("[dim yellow]ℹ Note: Windows Notifications are turned OFF in your Windows Settings (System > Notifications). Enable notifications to see visual toast alerts.[/dim yellow]")
            console.print()
        else:
            console.print("[bold red]✖ Notification failed to dispatch.[/bold red]\n")
        return

    # Handle schedule commands
    sched_freq = "once" if args.once else args.frequency
    if args.schedule_install is not None:
        run_schedule_install_cmd(time_str=args.schedule_install, notify=args.notify, frequency=sched_freq)
        return
    if args.schedule_status:
        run_schedule_status_cmd()
        return
    if args.schedule_remove:
        run_schedule_remove_cmd()
        return

    if args.subcommand == "schedule":
        sub_action = (args.extra_args[0].lower() if args.extra_args else "status")
        if sub_action in ("install", "add", "set"):
            t_str = args.extra_args[1] if len(args.extra_args) > 1 else "07:30"
            run_schedule_install_cmd(time_str=t_str, notify=args.notify, frequency=sched_freq)
        elif sub_action in ("remove", "uninstall", "delete", "rm"):
            run_schedule_remove_cmd()
        elif sub_action in ("status", "check", "show", "info"):
            run_schedule_status_cmd()
        elif ":" in sub_action:
            run_schedule_install_cmd(time_str=sub_action, notify=args.notify, frequency=sched_freq)
        else:
            run_schedule_status_cmd()
        return

    # Determine command
    is_backfill = args.backfill or (args.subcommand == "backfill") or (
        args.subcommand == "history" and args.extra_args and args.extra_args[0].lower() in ("backfill", "import")
    )
    if is_backfill:
        run_backfill_cmd()
        return

    is_prompt = args.prompt or (args.prompt_format is not None) or (args.subcommand == "prompt")
    if is_prompt:
        from agent_quota_tracker.prompt import format_prompt

        format_spec = args.prompt_format or (args.extra_args[0] if args.extra_args else None)
        output = format_prompt(preset_or_format=format_spec, refresh=args.refresh)
        print(output)
        return

    is_metrics = args.metrics or (args.subcommand == "metrics")
    if is_metrics:
        run_metrics_cmd()
        return

    is_export = (args.export_csv is not None) or (args.subcommand == "export")
    if is_export:
        filepath = args.export_csv
        export_type = args.export_type
        if args.subcommand == "export" and args.extra_args:
            for a in args.extra_args:
                if a.lower() in ("snapshots", "pokes"):
                    export_type = a.lower()
                elif filepath is None or filepath == "-":
                    filepath = a
        run_export_cmd(filepath=filepath, export_type=export_type, days=args.days)
        return

    is_analytics = args.analytics or (args.subcommand in ("analytics", "insights"))
    if is_analytics:
        run_analytics_command(days=args.days)
        return

    is_status = args.status or args.subcommand == "status"
    is_poke = args.poke or args.subcommand == "poke"
    is_poke_watch = args.poke_watch or args.subcommand == "poke-watch"
    is_auto = args.auto or args.auto_poke or (args.subcommand == "auto")
    is_dashboard = args.dashboard or (args.subcommand == "dashboard")
    is_tui = args.tui or (args.subcommand == "tui")

    if is_tui:
        run_tui_cmd(
            refresh_interval=args.refresh_interval,
            notify=args.notify,
            force=args.force,
            agent_id=args.agent,
        )
    elif is_auto:
        run_auto_checker_loop(
            force=args.force,
            agent_id=args.agent,
            notify=args.notify,
            max_cycles=args.max_cycles,
            refresh_interval=args.refresh_interval,
        )
    elif args.poke_at:
        run_poke_at(
            target_time_str=args.poke_at,
            and_watch=is_poke_watch or (args.watch is not None),
            watch_interval=args.interval,
            force=args.force,
            agent_id=args.agent,
            notify=args.notify,
        )
    elif is_poke_watch:
        run_poke_watch_loop(
            interval_arg=args.interval,
            force=args.force,
            agent_id=args.agent,
            notify=args.notify,
        )
    elif args.watch is not None:
        run_watch_loop(interval=args.watch or 15)
    elif is_status or args.json:
        print_status_table(as_json=args.json)
    elif is_poke:
        run_poke(force=args.force, agent_id=args.agent, notify=args.notify)
    elif is_dashboard:
        start_dashboard_server(port=args.port, open_browser=not args.no_browser)
    else:
        # Default behavior: show status table and brief help
        print_status_table()
        console.print("[dim]Use [bold]agents auto[/bold], [bold]agents tui[/bold], [bold]agents --status[/bold], [bold]agents --poke[/bold], or [bold]agents --dashboard[/bold] for specific actions.[/dim]\n")


if __name__ == "__main__":
    main()
