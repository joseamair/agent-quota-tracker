from __future__ import annotations

import argparse
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
from agent_quota_tracker.models import AgentStatus

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


def run_poke(force: bool = False, agent_id: Optional[str] = None) -> None:
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

    console.print()


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
        "subcommand",
        nargs="?",
        choices=["status", "poke", "dashboard"],
        help="Optional positional subcommand alias for --status, --poke, or --dashboard",
    )

    args = parser.parse_args()

    # Determine command
    is_status = args.status or args.subcommand == "status"
    is_poke = args.poke or args.subcommand == "poke"
    is_dashboard = args.dashboard or args.cmd == "dashboard" if hasattr(args, "cmd") else (args.dashboard or args.subcommand == "dashboard")

    if args.watch is not None:
        run_watch_loop(interval=args.watch or 15)
    elif is_status or args.json:
        print_status_table(as_json=args.json)
    elif is_poke:
        run_poke(force=args.force, agent_id=args.agent)
    elif is_dashboard:
        start_dashboard_server(port=args.port, open_browser=not args.no_browser)
    else:
        # Default behavior: show status table and brief help
        print_status_table()
        console.print("[dim]Use [bold]agents --status[/bold], [bold]agents --poke[/bold], or [bold]agents --dashboard[/bold] for specific actions.[/dim]\n")


if __name__ == "__main__":
    main()
