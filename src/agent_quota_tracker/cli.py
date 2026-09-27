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
        table.add_column("Wk Use", justify="right", style="dim", no_wrap=True)
        table.add_column("Weekly Reset", justify="left", style="cyan", no_wrap=True)

        for s in statuses:
            state_text = Text("● ACTIVE", style="bold green") if s.is_active else Text("○ INACTIVE", style="dim white")
            rem_text = Text(s.time_remaining_str, style="bold cyan") if s.is_active else Text("Ready to Poke", style="dim yellow")
            pct_val = round(s.used_percent, 1)
            pct_style = "bold red" if pct_val > 80 else ("bold yellow" if pct_val > 50 else "bold green")
            usage_text = Text(f"{pct_val}%", style=pct_style)
            weekly_text = f"{round(s.weekly_used_percent, 1)}%" if s.weekly_used_percent is not None else "-"
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
        table.add_column("Wk %", justify="right", style="dim", no_wrap=True)
        table.add_column("Weekly Reset", justify="left", style="cyan", no_wrap=True)

        for s in statuses:
            name = s.name.replace(" (AGY)", "").replace("Google Antigravity", "Antigravity")
            state_text = Text("● ACTIVE", style="bold green") if s.is_active else Text("○ INACTIVE", style="dim white")
            rem_text = Text(s.time_remaining_str, style="bold cyan") if s.is_active else Text("Ready", style="dim yellow")
            pct_val = round(s.used_percent, 1)
            pct_style = "bold red" if pct_val > 80 else ("bold yellow" if pct_val > 50 else "bold green")
            usage_text = Text(f"{pct_val}%", style=pct_style)
            weekly_text = f"{round(s.weekly_used_percent, 1)}%" if s.weekly_used_percent is not None else "-"

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
        table.add_column("Wk%", justify="right", style="dim", no_wrap=True)
        table.add_column("Weekly", justify="left", style="cyan", no_wrap=True)

        for s in statuses:
            name = s.name.replace("Google Antigravity (AGY)", "Antigravity").replace("OpenAI Codex", "Codex").replace("Claude (", "").replace(")", "")
            state_text = Text("● ACTIVE", style="bold green") if s.is_active else Text("○ INACT", style="dim white")
            parts = s.time_remaining_str.split()
            if len(parts) >= 2 and s.is_active:
                left_str = f"{parts[0]} {parts[1]}"
            else:
                left_str = s.time_remaining_str if s.is_active else "Ready"
            rem_text = Text(left_str, style="bold cyan") if s.is_active else Text("Ready", style="dim yellow")

            pct_val = int(round(s.used_percent))
            pct_style = "bold red" if pct_val > 80 else ("bold yellow" if pct_val > 50 else "bold green")
            usage_text = Text(f"{pct_val}%", style=pct_style)
            weekly_text = f"{int(round(s.weekly_used_percent))}%" if s.weekly_used_percent is not None else "-"

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
            state_text = Text("● ACT", style="bold green") if s.is_active else Text("○ OFF", style="dim white")
            parts = s.time_remaining_str.split()
            left_str = f"{parts[0]} {parts[1]}" if (len(parts) >= 2 and s.is_active) else (s.time_remaining_str if s.is_active else "Ready")
            rem_text = Text(left_str, style="bold cyan") if s.is_active else Text("Ready", style="dim yellow")
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


def print_status_table(as_json: bool = False, term_w: Optional[int] = None) -> None:
    statuses = get_all_statuses()
    if as_json:
        import json
        print(json.dumps([s.to_dict() for s in statuses], indent=2))
        return

    width = term_w or get_terminal_width()
    table = build_status_table(statuses, term_w=width)
    active_console = Console(legacy_windows=False, width=width)
    active_console.print()
    active_console.print(table)
    active_console.print()


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


def compute_adaptive_sleep_seconds(statuses: list[AgentStatus]) -> tuple[int, str]:
    """Computes intelligent sleep duration until the earliest active agent window expires."""
    active_with_time = [
        s for s in statuses
        if s.is_active and s.time_remaining_seconds > 0
    ]
    if not active_with_time:
        return 120, "All agents idle or freshly checked"

    earliest = min(active_with_time, key=lambda s: s.time_remaining_seconds)
    # Add a safety margin of 45 seconds so window has cleanly transitioned
    sleep_secs = max(60, earliest.time_remaining_seconds + 45)
    return sleep_secs, f"{earliest.name} ({format_duration(earliest.time_remaining_seconds)} left)"


def run_countdown(total_seconds: int, prefix: str) -> None:
    """Displays a ticking countdown line."""
    import time
    for rem in range(total_seconds, 0, -1):
        sys.stdout.write(f"\r  ⏳ {prefix}: {format_duration(rem)} remaining • Press Ctrl+C to stop   ")
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * 85 + "\r")
    sys.stdout.flush()


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
                sleep_secs, reason = compute_adaptive_sleep_seconds(statuses)

            wake_time = (datetime.now() + timedelta(seconds=sleep_secs)).strftime("%H:%M:%S")
            console.print(f"[cyan]Next check at [bold]{wake_time}[/bold][/cyan] [dim]({reason})[/dim]")
            run_countdown(sleep_secs, f"Next check at {wake_time}")
            cycle += 1
    except KeyboardInterrupt:
        sys.stdout.write("\r" + " " * 85 + "\r")
        sys.stdout.flush()
        console.print("\n[bold yellow]⚡ Poke watchdog mode stopped.[/bold yellow]\n")


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
        sys.stdout.write("\r" + " " * 85 + "\r")
        sys.stdout.flush()
        console.print("\n[bold yellow]⚡ Scheduled poke cancelled by user.[/bold yellow]\n")
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
        "subcommand",
        nargs="?",
        choices=["status", "poke", "dashboard", "poke-watch", "prompt", "schedule"],
        help="Optional positional subcommand alias for status, poke, dashboard, poke-watch, prompt, or schedule",
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
    is_prompt = args.prompt or (args.prompt_format is not None) or (args.subcommand == "prompt")
    if is_prompt:
        from agent_quota_tracker.prompt import format_prompt

        format_spec = args.prompt_format or (args.extra_args[0] if args.extra_args else None)
        output = format_prompt(preset_or_format=format_spec, refresh=args.refresh)
        print(output)
        return

    is_status = args.status or args.subcommand == "status"
    is_poke = args.poke or args.subcommand == "poke"
    is_poke_watch = args.poke_watch or args.subcommand == "poke-watch"
    is_dashboard = args.dashboard or (args.subcommand == "dashboard")

    if args.poke_at:
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
        console.print("[dim]Use [bold]agents --status[/bold], [bold]agents --poke[/bold], [bold]agents --poke-watch[/bold], or [bold]agents --dashboard[/bold] for specific actions.[/dim]\n")


if __name__ == "__main__":
    main()
