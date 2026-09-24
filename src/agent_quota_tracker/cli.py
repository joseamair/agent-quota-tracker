from __future__ import annotations

import argparse
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

console = Console(legacy_windows=False, width=135)


def format_reset_time(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "Ready to Poke"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        local_dt = dt.astimezone()
        now = datetime.now(local_dt.tzinfo)
        time_part = local_dt.strftime("%H:%M:%S")
        if local_dt.date() == now.date():
            return f"{time_part} (Today)"
        else:
            return local_dt.strftime("%b %d, %H:%M:%S")
    except Exception:
        return iso_str[:19] if iso_str else "N/A"


def print_status_table() -> None:
    statuses = get_all_statuses()

    table = Table(
        title="[bold cyan]⚡ AI Agents 5-Hour & Weekly Quota Status[/bold cyan]",
        header_style="bold magenta",
        border_style="bright_blue",
        show_lines=True,
    )

    table.add_column("Agent / Account", style="bold white", min_width=22)
    table.add_column("Provider", style="cyan", justify="center", width=10)
    table.add_column("5h Window", justify="center", width=14)
    table.add_column("Time Remaining", justify="right", style="bold", width=16)
    table.add_column("Next 5h Reset", justify="center", width=18)
    table.add_column("5h Usage", justify="right", width=10)
    table.add_column("Weekly Use", justify="right", style="dim", width=11)
    table.add_column("Weekly Reset (Hrs & Date)", justify="left", style="cyan", width=30)

    for s in statuses:
        # Window State
        if s.is_active:
            state_text = Text("● ACTIVE", style="bold green")
            rem_text = Text(s.time_remaining_str, style="bold cyan")
        else:
            state_text = Text("○ INACTIVE", style="dim white")
            rem_text = Text("Ready to Poke", style="dim yellow")

        # Usage %
        pct_val = round(s.used_percent, 1)
        if pct_val > 80:
            usage_text = Text(f"{pct_val}%", style="bold red")
        elif pct_val > 50:
            usage_text = Text(f"{pct_val}%", style="bold yellow")
        else:
            usage_text = Text(f"{pct_val}%", style="bold green")

        # Weekly
        weekly_text = f"{round(s.weekly_used_percent, 1)}%" if s.weekly_used_percent is not None else "-"
        weekly_reset = Text(s.weekly_reset_str, style="bold cyan" if s.weekly_reset_str != "-" else "dim")

        table.add_row(
            s.name,
            s.provider.upper(),
            state_text,
            rem_text,
            format_reset_time(s.resets_at),
            usage_text,
            weekly_text,
            weekly_reset,
        )

    console.print()
    console.print(table)
    console.print()


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

    if is_status:
        print_status_table()
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
