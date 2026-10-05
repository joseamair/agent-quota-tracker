from __future__ import annotations

import os
import re
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from agent_quota_tracker.core import get_all_statuses, poke_all
from agent_quota_tracker.models import AgentStatus, PokeResult
from agent_quota_tracker.notifications import are_notifications_enabled, send_notification
from agent_quota_tracker.trackers.base import calculate_weekly_reset, format_duration


def enable_windows_vt() -> None:
    """Enables virtual terminal / ANSI escape sequence processing on Windows consoles."""
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            h_stdout = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(h_stdout, ctypes.byref(mode)):
                # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                kernel32.SetConsoleMode(h_stdout, mode.value | 0x0004)
        except Exception:
            pass


def enter_alt_screen() -> None:
    """Switches to the terminal alternate screen buffer and hides the cursor."""
    enable_windows_vt()
    sys.stdout.write("\033[?1049h\033[?25l\033[2J\033[H")
    sys.stdout.flush()


def leave_alt_screen() -> None:
    """Restores the terminal primary screen buffer and shows the cursor."""
    sys.stdout.write("\033[?25h\033[?1049l\033[0m")
    sys.stdout.flush()


def read_key(timeout: float = 0.1) -> Optional[str]:
    """Cross-platform non-blocking key reader.
    Returns normalized key string: 'up', 'down', 'left', 'right', 'enter', 'esc', 'ctrl_c',
    or lowercase single char ('p', 'f', 'a', 'r', 'q', '?', 'h', etc.).
    """
    start = time.time()
    if os.name == "nt":
        import msvcrt
        while time.time() - start < timeout:
            if msvcrt.kbhit():
                try:
                    ch = msvcrt.getch()
                except Exception:
                    return None
                if ch in (b"\x00", b"\xe0"):
                    # Extended arrow key sequence
                    try:
                        ch2 = msvcrt.getch()
                    except Exception:
                        return None
                    if ch2 == b"H":
                        return "up"
                    elif ch2 == b"P":
                        return "down"
                    elif ch2 == b"K":
                        return "left"
                    elif ch2 == b"M":
                        return "right"
                    elif ch2 == b"S":
                        return "backspace"
                    return None
                elif ch == b"\r":
                    return "enter"
                elif ch == b"\x1b":
                    return "esc"
                elif ch == b"\x08":
                    return "backspace"
                elif ch == b"\x03":
                    return "ctrl_c"
                elif ch == b"\t":
                    return "tab"
                else:
                    try:
                        return ch.decode("utf-8", errors="ignore").lower()
                    except Exception:
                        return None
            time.sleep(0.015)
        return None
    else:
        # POSIX (Linux, macOS)
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        try:
            old_settings = termios.tcgetattr(fd)
        except Exception:
            # Stdin is not a tty (e.g. redirected or test pipe)
            time.sleep(timeout)
            return None

        try:
            tty.setcbreak(fd)
            r, _, _ = select.select([sys.stdin], [], [], max(0.0, timeout))
            if r:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    # Check if there are more characters for escape sequences
                    r2, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if r2:
                        seq = sys.stdin.read(2)
                        if seq == "[A":
                            return "up"
                        elif seq == "[B":
                            return "down"
                        elif seq == "[C":
                            return "right"
                        elif seq == "[D":
                            return "left"
                        elif seq == "[3":
                            return "backspace"
                        return "esc"
                    return "esc"
                elif ch == "\r" or ch == "\n":
                    return "enter"
                elif ch in ("\x7f", "\x08"):
                    return "backspace"
                elif ch == "\x03":
                    return "ctrl_c"
                elif ch == "\t":
                    return "tab"
                return ch.lower()
            return None
        finally:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass


def render_progress_bar(percent: float, width: int = 10) -> str:
    """Renders a compact colored Unicode progress bar."""
    clamped = max(0.0, min(100.0, percent))
    filled_blocks = int(round((clamped / 100.0) * width))
    empty_blocks = max(0, width - filled_blocks)
    filled_str = "█" * filled_blocks
    empty_str = "░" * empty_blocks

    if clamped >= 90.0:
        color = "\033[1;31m"  # Bold red
    elif clamped >= 75.0:
        color = "\033[1;33m"  # Bold yellow
    elif clamped > 0.0:
        color = "\033[1;32m"  # Bold green
    else:
        color = "\033[2m"     # Dim

    return f"{color}{filled_str}\033[2m{empty_str}\033[0m"


def format_reset_time_compact(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "Ready to Poke"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        local_dt = dt.astimezone()
        now = datetime.now(local_dt.tzinfo)
        time_part = local_dt.strftime("%H:%M:%S")
        if local_dt.date() == now.date():
            return f"{time_part} Today"
        elif local_dt.date() == (now + timedelta(days=1)).date():
            return f"{time_part} Tmrw"
        return local_dt.strftime("%b %d %H:%M")
    except Exception:
        return "Ready to Poke"


class AgentTUI:
    """Interactive full-screen terminal UI for agent quota monitoring and priming."""

    def __init__(
        self,
        refresh_interval: int = 15,
        notify: bool = False,
        force: bool = False,
        agent_id: Optional[str] = None,
    ) -> None:
        self.refresh_interval = max(5, refresh_interval)
        self.notify = notify
        self.force = force
        self.agent_id = agent_id
        self.statuses: list[AgentStatus] = []
        self.selected_index: int = 0
        self.running: bool = False
        self.show_help: bool = False
        self.filter_mode: bool = False
        self.filter_query: str = ""
        self.status_msg: str = "Ready. Use [↑/↓] or [k/j] to navigate, [p] to poke, [/] to filter, [?] for help."
        self.status_type: str = "info"  # 'info', 'success', 'warning', 'error'
        self.status_time: float = time.time()
        self.last_api_fetch: float = 0.0
        self.last_tick_time: float = 0.0
        self.cached_term_size: tuple[int, int] = (100, 30)
        self.is_busy: bool = False
        self.busy_msg: str = ""

    def set_status(self, msg: str, level: str = "info") -> None:
        self.status_msg = msg
        self.status_type = level
        self.status_time = time.time()

    def get_filtered_statuses(self) -> list[AgentStatus]:
        """Returns statuses matching current filter query across name, provider, id, or status."""
        if not self.filter_query.strip():
            return self.statuses
        q = self.filter_query.strip().lower()
        if q == "idle":
            return [s for s in self.statuses if not s.is_active]
        if q == "active":
            return [s for s in self.statuses if s.is_active]
        if q in ("expired", "auth"):
            return [s for s in self.statuses if s.auth_status in ("expired", "missing")]

        res: list[AgentStatus] = []
        for s in self.statuses:
            if (
                q in s.name.lower()
                or q in s.provider.lower()
                or q in s.id.lower()
                or q in s.category.lower()
                or q in s.status_label.lower()
            ):
                res.append(s)
        return res

    def fetch_statuses(self) -> None:
        """Fetches fresh statuses from provider APIs or local cache."""
        try:
            statuses = get_all_statuses()
            if self.agent_id:
                target = self.agent_id.lower()
                statuses = [s for s in statuses if s.id == target or s.id == f"claude-{target}"]
            self.statuses = statuses
            filtered = self.get_filtered_statuses()
            if filtered:
                self.selected_index = max(0, min(self.selected_index, len(filtered) - 1))
            else:
                self.selected_index = 0
            self.last_api_fetch = time.time()
            self.last_tick_time = time.time()
        except Exception as e:
            self.set_status(f"Error refreshing statuses: {e}", level="error")

    def tick_second(self) -> None:
        """Decrements second-by-second countdowns for active accounts without calling APIs."""
        for s in self.statuses:
            if s.is_active and s.time_remaining_seconds > 0:
                s.time_remaining_seconds = max(0, s.time_remaining_seconds - 1)
                s.time_remaining_str = format_duration(s.time_remaining_seconds)

    def get_selected_agent(self) -> Optional[AgentStatus]:
        filtered = self.get_filtered_statuses()
        if 0 <= self.selected_index < len(filtered):
            return filtered[self.selected_index]
        return None

    def poke_selected(self, force: bool = False) -> None:
        agent = self.get_selected_agent()
        if not agent:
            self.set_status("No agent selected to poke.", level="warning")
            return

        self.is_busy = True
        self.busy_msg = f"Poking {agent.name}..."
        # Render busy frame immediately
        self.render_frame()

        try:
            results = poke_all(force=force, agent_id=agent.id)
            if results:
                res = results[0]
                if res.action_taken == "poked":
                    self.set_status(f"✔ Primed {agent.name}: {res.message}", level="success")
                    if self.notify and are_notifications_enabled():
                        send_notification("⚡ Agent Quota Primed", f"Successfully primed {agent.name}!")
                elif res.action_taken == "skipped":
                    self.set_status(f"ℹ Skipped {agent.name}: {res.message}", level="warning")
                else:
                    self.set_status(f"✖ Failed {agent.name}: {res.message}", level="error")
            else:
                self.set_status(f"No result for {agent.name}.", level="warning")
        except Exception as e:
            self.set_status(f"Error poking {agent.name}: {e}", level="error")
        finally:
            self.is_busy = False
            self.fetch_statuses()

    def poke_all_idle(self) -> None:
        self.is_busy = True
        self.busy_msg = "Poking idle accounts..."
        self.render_frame()

        try:
            if not self.filter_query.strip():
                results = poke_all(force=False, agent_id=self.agent_id)
            else:
                filtered = self.get_filtered_statuses()
                target_idle = [s for s in filtered if not s.is_active and s.auth_status != "expired"]
                if not target_idle:
                    self.set_status("ℹ No idle accounts to prime in current view.", level="info")
                    return
                results = []
                for agent in target_idle:
                    r = poke_all(force=False, agent_id=agent.id)
                    if r:
                        results.extend(r)

            poked_names = [r.agent_name for r in results if r.action_taken == "poked"]
            skipped_count = sum(1 for r in results if r.action_taken == "skipped")
            if poked_names:
                msg = f"✔ Primed {len(poked_names)} agent(s): {', '.join(poked_names)}"
                self.set_status(msg, level="success")
                if self.notify and are_notifications_enabled():
                    send_notification("⚡ Agent Quota Primed", f"Successfully primed {len(poked_names)} account(s)!")
            else:
                self.set_status(f"ℹ No idle accounts primed ({skipped_count} skipped/active).", level="info")
        except Exception as e:
            self.set_status(f"Error poking all idle: {e}", level="error")
        finally:
            self.is_busy = False
            self.fetch_statuses()

    def render_to_string(self, term_width: int, term_height: int) -> str:
        """Renders the complete ANSI frame for the terminal."""
        width = max(80, term_width)
        lines: list[str] = []

        filtered = self.get_filtered_statuses()

        # ── 1. Top Header Banner ───────────────────────────────────────────
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        active_count = sum(1 for s in self.statuses if s.is_active)
        total_count = len(self.statuses)

        # Compute earliest reset target
        active_with_time = [s for s in self.statuses if s.is_active and s.time_remaining_seconds > 0]
        if active_with_time:
            earliest = min(active_with_time, key=lambda s: s.time_remaining_seconds)
            earliest_str = f"{earliest.name} ({format_duration(earliest.time_remaining_seconds)})"
        else:
            earliest_str = "None (All idle)"

        header_title = "⚡ AGENT QUOTA TRACKER TUI"
        if self.filter_query:
            header_stats = f"Filter: '{self.filter_query}' ({len(filtered)}/{total_count}) • Active: {active_count}/{total_count} • {now_str}"
        else:
            header_stats = f"Active: {active_count}/{total_count} • Next Reset: {earliest_str} • {now_str}"

        # Truncate stats if line exceeds width
        if len(header_title) + len(header_stats) + 4 > width:
            header_stats = f"Active: {active_count}/{total_count} • {now_str}"

        left_pad = header_title
        right_pad = header_stats
        space_len = max(2, width - len(left_pad) - len(right_pad) - 2)

        lines.append(f"\033[1;36m┌{'─' * (width - 2)}┐\033[0m")
        lines.append(
            f"\033[1;36m│\033[0m \033[1;37m{left_pad}\033[0m"
            + (" " * space_len)
            + f"\033[dim]{right_pad}\033[0m \033[1;36m│\033[0m"
        )
        lines.append(f"\033[1;36m├{'─' * (width - 2)}┤\033[0m")

        # ── 2. Table Column Headers ────────────────────────────────────────
        col_cursor = "  "
        col_name_w = 26
        col_prov_w = 8
        col_state_w = 11
        col_rem_w = 12
        col_reset_w = 18
        col_bar_w = 10
        col_5h_w = 17  # Bar + %
        col_wk_w = 9
        col_wkreset_w = 16
        col_auth_w = 11

        tbl_hdr = (
            f"  \033[1;37m{'Agent / Account':<{col_name_w}} "
            f"{'Provider':<{col_prov_w}} "
            f"{'5h State':<{col_state_w}} "
            f"{'5h Left':<{col_rem_w}} "
            f"{'5h Reset':<{col_reset_w}} "
            f"{'5h Usage':<{col_5h_w}} "
            f"{'Wk Use':<{col_wk_w}} "
            f"{'Weekly Reset':<{col_wkreset_w}} "
            f"{'Auth':<{col_auth_w}}\033[0m"
        )
        lines.append(f"\033[1;36m│\033[0m{tbl_hdr:<{width + 8}}\033[1;36m│\033[0m")
        lines.append(f"\033[1;36m├{'─' * (width - 2)}┤\033[0m")

        # ── 3. Table Rows ──────────────────────────────────────────────────
        if not filtered:
            if self.filter_query:
                empty_msg = f"No accounts matching filter: '{self.filter_query}' (Press [Esc] to clear)."
            else:
                empty_msg = "No accounts configured or loaded."
            lines.append(f"\033[1;36m│\033[0m \033[dim]{empty_msg:<{width - 4}}\033[0m \033[1;36m│\033[0m")
        else:
            for idx, s in enumerate(filtered):
                is_selected = (idx == self.selected_index)
                cursor = "▶ " if is_selected else "  "

                # Agent Name
                name_disp = s.name[:col_name_w].ljust(col_name_w)

                # Provider
                prov_disp = s.provider.upper()[:col_prov_w].ljust(col_prov_w)

                # 5h State
                if s.auth_status == "expired":
                    state_disp = "\033[1;31m⚠️ EXPIRED \033[0m"
                elif s.auth_status == "missing":
                    state_disp = "\033[1;33m⚠️ NO AUTH \033[0m"
                elif s.is_active:
                    state_disp = "\033[1;32m● ACTIVE  \033[0m"
                else:
                    state_disp = "\033[1;33m○ INACTIVE\033[0m"

                # 5h Left
                if s.is_active and s.time_remaining_seconds > 0:
                    rem_disp = s.time_remaining_str[:col_rem_w].ljust(col_rem_w)
                else:
                    rem_disp = "--          "

                # 5h Reset
                reset_disp = format_reset_time_compact(s.resets_at)[:col_reset_w].ljust(col_reset_w)

                # 5h Usage Bar + %
                bar = render_progress_bar(s.used_percent, width=col_bar_w)
                pct_str = f"{s.used_percent:5.1f}%"
                bar_combined = f"{bar} {pct_str}"

                # Weekly Usage
                if s.weekly_used_percent is not None:
                    wk_pct = s.weekly_used_percent
                    wk_col = "\033[1;31m" if wk_pct >= 90.0 else ("\033[1;33m" if wk_pct >= 75.0 else "\033[0m")
                    wk_disp = f"{wk_col}{wk_pct:5.1f}%\033[0m   "
                else:
                    wk_disp = "--       "

                # Weekly Reset
                wk_reset_disp = s.weekly_reset_str[:col_wkreset_w].ljust(col_wkreset_w)

                # Auth status
                if s.auth_status == "valid":
                    auth_disp = "\033[1;32mOK       \033[0m"
                elif s.auth_status == "expired":
                    auth_disp = "\033[1;31mEXPIRED  \033[0m"
                elif s.auth_status == "missing":
                    auth_disp = "\033[1;33mLOGIN REQ\033[0m"
                else:
                    auth_disp = f"{s.auth_status[:col_auth_w]:<{col_auth_w}}"

                row_content = (
                    f"{cursor}{name_disp} {prov_disp} {state_disp} {rem_disp} {reset_disp} "
                    f"{bar_combined} {wk_disp} {wk_reset_disp} {auth_disp}"
                )

                if is_selected:
                    # Highlight selected row with reverse style or bright highlight
                    highlighted_line = f"\033[1;36m│\033[0m\033[7m{row_content:<{width - 2}}\033[0m\033[1;36m│\033[0m"
                    lines.append(highlighted_line)
                else:
                    lines.append(f"\033[1;36m│\033[0m{row_content:<{width + 12}}\033[1;36m│\033[0m")

        # ── 4. Inspector Panel for Selected Account ────────────────────────
        lines.append(f"\033[1;36m├{'─' * (width - 2)}┤\033[0m")
        sel = self.get_selected_agent()
        if sel:
            cat_str = sel.category.capitalize()
            insp_title = f"🔍 Account Inspector: \033[1;37m{sel.name}\033[0m (ID: \033[cyan]{sel.id}\033[0m • {cat_str})"
            lines.append(f"\033[1;36m│\033[0m {insp_title:<{width + 6}}\033[1;36m│\033[0m")

            # Line 1: 5h Window info
            w_state = "Active Window" if sel.is_active else "Idle / Ready to Poke"
            w_color = "\033[1;32m" if sel.is_active else "\033[1;33m"
            l1 = f"5h Status: {w_color}{w_state}\033[0m • Remaining: \033[1m{sel.time_remaining_str}\033[0m • Resets At: \033[1m{sel.resets_at or 'None'}\033[0m"
            lines.append(f"\033[1;36m│\033[0m   {l1:<{width + 8}}\033[1;36m│\033[0m")

            # Line 2: Utilization metrics
            l2 = (
                f"Utilization: 5-Hour: \033[1m{sel.used_percent}%\033[0m • "
                f"Weekly: \033[1m{sel.weekly_used_percent if sel.weekly_used_percent is not None else '--'}%\033[0m • "
                f"Weekly Reset: \033[1m{sel.weekly_reset_str}\033[0m"
            )
            lines.append(f"\033[1;36m│\033[0m   {l2:<{width + 8}}\033[1;36m│\033[0m")

            # Line 3: Auth & Remediation
            if sel.auth_status != "valid" and sel.remediation_hint:
                auth_color = "\033[1;31m" if sel.auth_status == "expired" else "\033[1;33m"
                l3 = f"Auth Status: {auth_color}{sel.auth_status.upper()}\033[0m • Action Required: \033[1;33m{sel.remediation_hint}\033[0m"
            else:
                l3 = f"Auth Status: \033[1;32mVALID\033[0m • Token credentials ready for CLI queries."
            lines.append(f"\033[1;36m│\033[0m   {l3:<{width + 8}}\033[1;36m│\033[0m")
        else:
            lines.append(f"\033[1;36m│\033[0m   \033[dim]No account selected.\033[0m{' ' * (width - 25)}\033[1;36m│\033[0m")

        # ── 5. Status / Activity Message Bar ──────────────────────────────
        lines.append(f"\033[1;36m├{'─' * (width - 2)}┤\033[0m")
        if self.filter_mode:
            status_line = f"\033[1;33m🔍 Filter:\033[0m \033[1;37m{self.filter_query}\033[0m\033[7m \033[0m  \033[dim](Type to search, [Enter] apply, [Esc] clear)\033[0m"
        elif self.is_busy:
            status_line = f"\033[1;33m⏳ {self.busy_msg}\033[0m"
        elif self.filter_query:
            status_line = f"\033[1;33m🔍 Filter: '{self.filter_query}'\033[0m \033[dim]({len(filtered)}/{total_count} shown • [/] edit, [Esc] clear)\033[0m • {self.status_msg}"
        elif self.status_type == "success":
            status_line = f"\033[1;32m{self.status_msg}\033[0m"
        elif self.status_type == "warning":
            status_line = f"\033[1;33m{self.status_msg}\033[0m"
        elif self.status_type == "error":
            status_line = f"\033[1;31m{self.status_msg}\033[0m"
        else:
            status_line = f"\033[cyan]{self.status_msg}\033[0m"

        clean_status = re.sub(r"\033\[[0-9;]*m", "", status_line)
        status_pad = max(0, width - 4 - len(clean_status))
        lines.append(f"\033[1;36m│\033[0m {status_line}{' ' * status_pad} \033[1;36m│\033[0m")

        # ── 6. Bottom Hotkey Helper Bar ────────────────────────────────────
        lines.append(f"\033[1;36m├{'─' * (width - 2)}┤\033[0m")
        hotkeys = (
            "\033[1;37m[↑/↓]\033[0m Nav  "
            "\033[1;32m[p]\033[0m Poke  "
            "\033[1;33m[f]\033[0m Force  "
            "\033[1;36m[a]\033[0m All  "
            "\033[1;33m[/]\033[0m Filter  "
            "\033[1;37m[r]\033[0m Refresh  "
            "\033[1;35m[?]\033[0m Help  "
            "\033[1;31m[q]\033[0m Quit"
        )
        clean_hotkeys = re.sub(r"\033\[[0-9;]*m", "", hotkeys)
        hk_pad = max(0, width - 4 - len(clean_hotkeys))
        lines.append(f"\033[1;36m│\033[0m {hotkeys}{' ' * hk_pad} \033[1;36m│\033[0m")
        lines.append(f"\033[1;36m└{'─' * (width - 2)}┘\033[0m")

        # ── 7. Optional Help Modal Overlay ────────────────────────────────
        if self.show_help:
            lines = self.overlay_help_modal(lines, width, term_height)

        return "\n".join(lines)

    def overlay_help_modal(self, lines: list[str], width: int, height: int) -> list[str]:
        """Renders a floating help modal over the center of the screen."""
        modal_w = min(74, width - 4)
        help_content = [
            "┌" + ("─" * (modal_w - 2)) + "┐",
            "│" + " ⚡ AGENT QUOTA TRACKER TUI — KEYBOARD REFERENCE ".center(modal_w - 2) + "│",
            "├" + ("─" * (modal_w - 2)) + "┤",
            "│" + "  Navigation & Filtering:".ljust(modal_w - 2) + "│",
            "│" + "    ↑ / k       Move selection up".ljust(modal_w - 2) + "│",
            "│" + "    ↓ / j       Move selection down".ljust(modal_w - 2) + "│",
            "│" + "    /           Quick filter (name, provider, idle/active/expired)".ljust(modal_w - 2) + "│",
            "│" + "    Esc         Clear active filter (or close modal/quit)".ljust(modal_w - 2) + "│",
            "│" + " ".ljust(modal_w - 2) + "│",
            "│" + "  Actions & Priming:".ljust(modal_w - 2) + "│",
            "│" + "    p           Poke selected account (starts 5h rolling window)".ljust(modal_w - 2) + "│",
            "│" + "    f           Force poke selected account (even if active)".ljust(modal_w - 2) + "│",
            "│" + "    a           Poke all idle accounts in current view".ljust(modal_w - 2) + "│",
            "│" + "    r           Manual instant refresh from OAuth APIs & cache".ljust(modal_w - 2) + "│",
            "│" + "    ? or h      Toggle this help modal".ljust(modal_w - 2) + "│",
            "│" + "    q           Quit TUI and return to shell".ljust(modal_w - 2) + "│",
            "│" + " ".ljust(modal_w - 2) + "│",
            "│" + "  5-Hour Rolling Threshold Mechanics:".ljust(modal_w - 2) + "│",
            "│" + "    • Idle accounts show ○ INACTIVE. The first prompt trips the meter.".ljust(modal_w - 2) + "│",
            "│" + "    • Priming early provides double-quota coverage during peak hours.".ljust(modal_w - 2) + "│",
            "│" + "    • Quota utilization updates locally every 1s & APIs every 15s.".ljust(modal_w - 2) + "│",
            "│" + " ".ljust(modal_w - 2) + "│",
            "│" + "               Press [?] or [q] or [Esc] to close                ".center(modal_w - 2) + "│",
            "└" + ("─" * (modal_w - 2)) + "┘",
        ]

        # Ensure lines has enough vertical space for the modal
        min_lines_needed = len(help_content) + 2
        while len(lines) < min_lines_needed:
            lines.append(f"\033[1;36m│\033[0m{' ' * (width - 2)}\033[1;36m│\033[0m")

        # Calculate vertical insertion point
        start_y = max(1, (len(lines) - len(help_content)) // 2)
        start_x = max(0, (width - modal_w) // 2)

        for i, hline in enumerate(help_content):
            target_idx = start_y + i
            if target_idx < len(lines):
                # Replace segment on lines[target_idx]
                lines[target_idx] = (" " * start_x) + "\033[1;33m" + hline + "\033[0m"

        return lines

    def render_frame(self) -> None:
        """Paints the current state to the terminal using home cursor position."""
        cols, rows = shutil.get_terminal_size(fallback=(100, 30))
        output = self.render_to_string(cols, rows)
        # Position cursor at top-left and draw frame
        sys.stdout.write(f"\033[H{output}\033[K")
        sys.stdout.flush()

    def run(self, max_cycles: Optional[int] = None) -> None:
        """Main execution loop for interactive TUI."""
        enter_alt_screen()
        self.running = True
        self.fetch_statuses()

        cycle = 0
        try:
            while self.running:
                if max_cycles is not None and cycle >= max_cycles:
                    break

                now_ts = time.time()

                # 1. Check for periodic API refresh
                if now_ts - self.last_api_fetch >= self.refresh_interval:
                    self.fetch_statuses()

                # 2. Check for local 1-second countdown tick
                if now_ts - self.last_tick_time >= 1.0:
                    self.tick_second()
                    self.last_tick_time = now_ts

                # 3. Render screen
                self.render_frame()

                # 4. Read non-blocking input
                key = read_key(timeout=0.1)
                if key:
                    self.handle_key(key)

                cycle += 1
        except KeyboardInterrupt:
            pass
        finally:
            leave_alt_screen()
            sys.stdout.write("\033[1;32m✔ Returned from Agent Quota Tracker TUI.\033[0m\n")
            sys.stdout.flush()

    def handle_key(self, key: str) -> None:
        """Dispatches keypress actions."""
        if self.show_help:
            if key in ("?", "h", "q", "esc", "enter"):
                self.show_help = False
            return

        if self.filter_mode:
            if key == "esc":
                self.filter_query = ""
                self.filter_mode = False
                self.selected_index = 0
                self.set_status("Filter cleared.", level="info")
            elif key == "enter":
                self.filter_mode = False
                self.selected_index = 0
                if self.filter_query:
                    self.set_status(f"Filter active: '{self.filter_query}'. Press [/] to edit, [Esc] to clear.", level="info")
                else:
                    self.set_status("Filter cleared.", level="info")
            elif key == "backspace":
                if self.filter_query:
                    self.filter_query = self.filter_query[:-1]
                self.selected_index = 0
            elif len(key) == 1 and (key.isalnum() or key in (" ", "-", "_", ".", "@", ":")):
                self.filter_query += key
                self.selected_index = 0
            return

        filtered = self.get_filtered_statuses()
        if key in ("up", "k"):
            if filtered:
                self.selected_index = (self.selected_index - 1) % len(filtered)
        elif key in ("down", "j"):
            if filtered:
                self.selected_index = (self.selected_index + 1) % len(filtered)
        elif key == "/":
            self.filter_mode = True
            self.set_status("Type to filter accounts (Enter: apply, Esc: clear).", level="info")
        elif key == "esc":
            if self.filter_query:
                self.filter_query = ""
                self.selected_index = 0
                self.set_status("Filter cleared.", level="info")
            else:
                self.running = False
        elif key == "p":
            self.poke_selected(force=False)
        elif key == "f":
            self.poke_selected(force=True)
        elif key == "a":
            self.poke_all_idle()
        elif key == "r":
            self.set_status("Refreshing quota statuses from APIs...", level="info")
            self.fetch_statuses()
            self.set_status("✔ Quota statuses refreshed.", level="success")
        elif key in ("?", "h"):
            self.show_help = True
        elif key in ("q", "ctrl_c"):
            self.running = False


def run_tui(
    refresh_interval: int = 15,
    notify: bool = False,
    force: bool = False,
    agent_id: Optional[str] = None,
) -> None:
    """Entry point to launch the Agent Quota Tracker interactive full-screen TUI."""
    app = AgentTUI(
        refresh_interval=refresh_interval,
        notify=notify,
        force=force,
        agent_id=agent_id,
    )
    app.run()
