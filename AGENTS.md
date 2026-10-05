# 🤖 Agent Operational Guide & Autonomous Scheduling Architecture

This document provides a comprehensive technical overview of the AI coding agents supported by `agent-quota-tracker`, their quota mechanisms, the smart poke verification engine, and autonomous watchdog/scheduled priming architectures.

---

## 📑 Table of Contents

1. [Supported AI Agent Ecosystem](#1-supported-ai-agent-ecosystem)
2. [5-Hour Rolling Threshold Window Mechanics](#2-5-hour-rolling-threshold-window-mechanics)
3. [Verified Smart Poke Engine](#3-verified-smart-poke-engine)
4. [The Peak-Time Quota Maximization Strategy](#4-the-peak-time-quota-maximization-strategy)
5. [Roadmap Architecture: Autonomous Watchdog & Target-Time Scheduling](#5-roadmap-architecture-autonomous-watchdog--target-time-scheduling)
   - [Feature 1: Automated Poke Watchdog Mode (`--poke-watch`)](#feature-1-automated-poke-watchdog-mode---poke-watch)
   - [Feature 2: Scheduled Target-Time Morning Priming (`--poke-at`)](#feature-2-scheduled-target-time-morning-priming---poke-at)
6. [Security & Isolation Principles](#6-security--isolation-principles)

---

## 1. Supported AI Agent Ecosystem

`agent-quota-tracker` unifies multi-account monitoring across leading AI developer tools:

| Agent / Account | Provider | Interface / Protocol | Quota Extraction Method |
|---|---|---|---|
| **Google Antigravity (AGY)** | Google | CLI subshell (`agy`) | Local CLI query: `agy -p "/usage" --output-format json` |
| **OpenAI Codex** | OpenAI | Local JSON-RPC Daemon (`codex`) | App-server RPC request: `account/rateLimits/read` |
| **Claude (Multi-Account via CCS)** | Anthropic | CCS (`~/.ccs/instances/<profile>`) | Direct HTTPS OAuth: `api.anthropic.com/api/oauth/usage` |
| **Claude (Standard Single-Account)** | Anthropic | Official CLI (`~/.claude/`) | Direct HTTPS OAuth with fallback to `claude -p` |

### Claude Integration Modes: CCS vs Standard CLI
1. **Multi-Account Mode (`ccs`)**:
   - Engineered for developers juggling multiple Anthropic Claude accounts (e.g., personal vs. work).
   - Powered by the [Claude Code Switcher (`ccs`)](https://github.com/joseamair/ccs) utility.
   - Credentials and cached states reside under `~/.ccs/instances/<profile>/.credentials.json` and `.claude.json`.
   - The default configuration of this repository tracks 5 accounts: AGY, Codex, and 3 CCS profiles (`personal`, `work`, `work2`).
2. **Standard Single-Account Mode (Official Claude CLI)**:
   - For environments with a single official Anthropic Claude CLI installation on Windows (`claude.exe`), Linux, or macOS.
   - Automatically discovers credentials from `~/.claude/.credentials.json` (or `~/.claude.json`).
   - If CCS is not installed or the profile is omitted/set to `"default"`, the smart poke engine invokes `claude -p "Hello, how are you doing?"` directly.
   - **Token Refresh**: If the stored OAuth token has expired (`401 OAuth access token has expired`), running `claude login` refreshes the token in `~/.claude/.credentials.json`.

---

## 2. 5-Hour Rolling Threshold Window Mechanics

Each provider operates on a **5-hour rolling threshold window**:
- When an agent is **idle** and no queries have been made, its quota window is dormant.
- The **first interaction** (even a 1-token prompt) trips the quota meter and starts an exact 5-hour countdown.
- At the end of 5 hours, the utilization counter resets to 0%, and the window becomes dormant again until the next user or automated prompt.

```text
[Idle State: ○ INACTIVE] ──(Poke / First Query)──► [● ACTIVE: 5h Window Counting Down]
                                                               │
                                                               ▼ (After 5 Hours)
                                                    [Reset to 0% Utilization]
                                                               │
                                                               ▼
                                                    [Idle State: ○ INACTIVE]
```

### Provider-Specific Idle Quirks Handled by the Tracker
- **OpenAI Codex**: When idle (`0.0%` usage), Codex's app-server dynamically reports a sliding prospective `resetsAt = now + 5 hours`. The tracker verifies whether usage is non-zero or if a verified poke occurred before marking as `● ACTIVE`.
- **Google Antigravity (AGY)**: Similarly, AGY reports `remaining_fraction: 1.0` with a sliding future timestamp. The tracker inspects both utilization and poke cache history within a grace window to distinguish genuine active windows from idle dormant states.

---

## 3. Verified Smart Poke Engine

The poke engine (`agents --poke`) safely primes dormant 5-hour quota windows without exhausting expensive generation limits:
1. **Window Guard**: Inspects current active states; active accounts are immediately skipped to preserve token economy.
2. **Weekly Quota Exhaustion Guard**: If an account has reached $\ge 100\%$ weekly utilization (or has a provider lockout reason), `--poke` automatically skips it to prevent exhausting the remaining emergency buffer on a greeting prompt (overridable with `--force`).
3. **Lightweight Invocation**:
   - Anthropic Claude: Dispatches `ccs <profile> -p "Hello, how are you doing?"` (or `claude -p` for standard single-account setups) with `stdin=DEVNULL`.
   - OpenAI Codex: Dispatches non-interactive query via `codex exec`.
   - Google Antigravity: Dispatches non-interactive query via `agy prompt`.
4. **Response Verification**: Waits for the model to reply, extracts a single-line summary (e.g. `↳ Reply: "I am doing well, ready to help..."`), and instantly re-queries the provider usage API to confirm the 5-hour window is live.

---

## 4. The Peak-Time Quota Maximization Strategy

For software engineers working full workdays, **when** you start your 5-hour window determines whether you get **one** or **two** full quota allocations during your peak working hours.

### The Unscheduled Scenario (No Morning Poke)
- 09:00 AM: You sit down and send your first prompt. Window 1 starts.
- 09:00 AM – 02:00 PM: You consume your 5-hour quota.
- 02:00 PM: Window 1 expires and resets.
- 02:00 PM – 05:00 PM: You consume Window 2 until you log off.
- **Problem**: Between 11:00 AM and 01:00 PM (peak morning/afternoon coding), if you exhaust your tokens, you are locked out until 02:00 PM.

### The Strategic Primed Scenario (Poke at 07:30 AM)
- 07:30 AM: Automated poke fires before your workday starts while your machine is running. Window 1 starts counting down.
- 09:00 AM: You log in. You have full 100% quota available with **3.5 hours remaining** on Window 1.
- 12:30 PM: Exactly at lunch / start of afternoon deep work, **Window 1 resets** back to 100%!
- 12:30 PM – 05:30 PM: You receive a completely fresh second quota allocation covering your entire afternoon peak.
- **Outcome**: Seamless double-quota coverage during peak workday hours without midday lockouts.

---

## 5. Roadmap Architecture: Autonomous Watchdog & Target-Time Scheduling

To automate this strategy without manual terminal loops, the following features have been implemented and released in **v1.1.0**, **v1.2.0**, **v1.2.1**, **v1.3.0**, and **v1.4.0**:

### Feature 1: Automated Poke Watchdog Mode (`--poke-watch`) [DELIVERED - v1.1.0]
- **Tracking Issue**: [#18](https://github.com/joseamair/agent-quota-tracker/issues/18)
- **Command**: `agents --poke-watch [--interval <duration>]`
- **Architecture**:
  - Replaces fragile shell loops (`while ($true) { agents --poke; Start-Sleep ... }`).
  - **Adaptive Sleep Engine**: Computes $\Delta t = \min(\text{active\_windows\_remaining}) + 45\text{s}$. If Claude Work expires in 22 minutes, the watchdog sleeps for ~23 minutes, immediately waking up to prime the account the moment it turns idle.
  - Interactive terminal UI displaying ticking countdown to next check and last action log.
  - Clean interrupt handling (`Ctrl+C`) with zero orphaned background processes.

### Feature 2: Scheduled Target-Time Morning Priming (`--poke-at`) [DELIVERED - v1.1.0]
- **Tracking Issue**: [#19](https://github.com/joseamair/agent-quota-tracker/issues/19)
- **Command**: `agents --poke-at HH:MM` (e.g., `agents --poke-at 07:30`)
- **Architecture**:
  - Accepts a 24-hour target time (`HH:MM`).
  - Automatically calculates overnight delta if target time is the next morning.
  - Displays a clean sleeping countdown until target execution.
  - At target time, executes a verified poke across all idle accounts, prints the status report, and exits cleanly.
  - Native cross-platform support across Python, standalone runner, and pure PowerShell (`agents_native.ps1`).

### Feature 3: Native Desktop Toast Notifications (`--notify`, `--test-notify`) [DELIVERED - v1.2.0]
- **Tracking Issue**: [#20](https://github.com/joseamair/agent-quota-tracker/issues/20)
- **Command**: `agents --notify` (`-n`), `agents --test-notify`
- **Architecture**:
  - Zero third-party dependencies: uses native Windows WinRT XML toast notifications (`ToastText02`), macOS `osascript`, and Linux `notify-send`.
  - Dispatches notifications on successful priming (`--poke`), cooldown expirations in watchdog daemon (`--poke-watch`), and scheduled target times (`--poke-at`).
  - Automatic detection and friendly warning when Windows Notifications master toggle is disabled in system settings.
  - Native cross-platform support across Python package, standalone `agents.py`, and pure PowerShell (`agents_native.ps1`).

### Feature 4: Shell Prompt & Status Bar Integration (`--prompt`, `--prompt-format`) [DELIVERED - v1.2.0]
- **Tracking Issue**: [#25](https://github.com/joseamair/agent-quota-tracker/issues/25)
- **Command**: `agents --prompt`, `agents --prompt-format <preset|template>`, `agents prompt`
- **Architecture**:
  - Ultra-fast (<15ms) cached status segments for **Starship**, **Oh-My-Posh**, **tmux**, and **PowerShell `$PROFILE`**.
  - Built-in presets: `default` (`[⚡ 3/5 Active • 2h14m]`), `compact` (`⚡3/5 2h14m`), `minimal` (`🤖 3/5`), `tmux`, and `json`.
  - Dynamic mathematical countdown calculation from cached timestamps without background daemon or polling.
  - Zero-overhead cache under `~/.agent_quota_tracker/cache.json`, auto-updated on status, poke, and watchdog cycles.
  - Native cross-platform support across Python package, standalone `agents.py`, and pure PowerShell (`agents_native.ps1`).

### Feature 5: OS-Level Scheduled Task Generator (`--schedule-install`) [DELIVERED - v1.2.0]
- **Tracking Issue**: [#22](https://github.com/joseamair/agent-quota-tracker/issues/22)
- **Command**: `agents --schedule-install [HH:MM]`, `agents --schedule-status`, `agents --schedule-remove`, `agents schedule ...`
- **Architecture**:
  - Registers, inspects, and uninstalls unattended OS-level morning priming background tasks.
  - Native cross-platform scheduler integrations:
    - **Windows**: Windows Task Scheduler (`ScheduledTasks` PowerShell cmdlets) operating safely in user space without UAC elevation.
    - **Linux**: User `crontab` (`crontab -l` / `crontab -`).
    - **macOS**: `launchd` LaunchAgent plist (`~/Library/LaunchAgents/com.agentquotatracker.priming.plist`).
  - Persistent run logging to `~/.agent_quota_tracker/schedule.log` capturing timestamped installations, poke outcomes, and task removals.
  - Zero third-party dependencies; full Tri-Engine Parity across Python package, standalone `agents.py`, and pure PowerShell (`agents_native.ps1`).

### Feature 6: Autonomous Continuous Auto-Checker Loop (`agents auto`, `--auto-poke`) [DELIVERED - v1.2.0, UPDATED - v1.2.1]
- **Tracking Issues**: [#31](https://github.com/joseamair/agent-quota-tracker/issues/31), [#42](https://github.com/joseamair/agent-quota-tracker/pull/42)
- **Command**: `agents auto`, `agents --auto`, `agents --auto-poke` (options: `--refresh-interval 15` / `-ri 15`, `--notify` / `-n`)
- **Architecture**:
  - Continuous autonomous monitoring and priming task that:
    1. Immediately primes any accounts that are currently idle and ready to poke (skipping accounts with $\ge 100\%$ weekly usage).
    2. Displays and live-updates the full status table in-place using ANSI redraw / `rich.live.Live` with second-by-second countdowns for all active accounts.
    3. Runs background zero-prompt-token quota refetching (configurable via `--refresh-interval`, default 15s) querying local cache and provider OAuth usage endpoints to keep `5h%` and `Wk%` numbers fresh as coding work continues.
    4. Features Early Idle Detection: automatically trips immediate window priming if an account's quota resets or cools down earlier than the scheduled timer.
    5. Computes earliest reset time and displays a live ticking terminal countdown: `⏳ Next poke target: <HH:MM:SS> (<Agent Name> (<time> left)) • Press Ctrl+C to stop`.
    6. When the countdown completes, automatically primes newly available quota windows and repeats the cycle endlessly.
  - Clean `Ctrl+C` interrupt handling with zero orphaned processes.
  - Zero third-party dependencies; full Tri-Engine Parity across modular Python package (`run_auto_checker_loop`), standalone runner (`agents.py`), and pure native PowerShell (`agents_native.ps1 -Auto`).

### Feature 7: Web Dashboard v2 with Real-Time SSE & Interactive Controls [DELIVERED - v1.2.0]
- **Tracking Issue**: [#24](https://github.com/joseamair/agent-quota-tracker/issues/24)
- **Command**: `agents --dashboard`, `agents -d`
- **Architecture**:
  - Real-time Server-Sent Events (SSE) push updates via `/api/stream` with zero-latency instant updates upon actions and graceful polling fallback.
  - Interactive UI controls: per-card "⚡ Poke" and "⚡ Force Poke" buttons with loading state feedback, plus header "⚡ Poke All Idle".
  - Morning Priming Configuration Modal: Glassmorphic interactive modal to inspect, configure, install, and remove OS-level daily morning priming background tasks (`/api/schedule`).
  - Multi-theme engine: Switch seamlessly between Glassmorphism Dark (default), Cyberpunk OLED, and Minimal Light with `localStorage` persistence.
  - Client-side ticking countdown timers on each active card.
  - Full Tri-Engine Parity across modular Python package (`src/agent_quota_tracker/dashboard.py`), standalone runner (`agents.py`), and pure native PowerShell (`agents_native.ps1 -Dashboard`).

### Feature 8: Additional Agent Trackers (Cursor, Windsurf, Copilot, Aider) [DELIVERED - v1.2.0 Beta, GA - v1.4.0]
- **Tracking Issues**: [#21](https://github.com/joseamair/agent-quota-tracker/issues/21), [#53](https://github.com/joseamair/agent-quota-tracker/issues/53)
- **Architecture**:
  - Modular integrations for **Cursor** (`api2.cursor.sh/auth/usage` with SQLite token extraction + `CURSOR_ACCESS_TOKEN` / `CURSOR_SESSION_COOKIE`), **Windsurf** (`api.codeium.com/register_user/` with `~/.codeium/config.json` + `CODEIUM_API_KEY`), **GitHub Copilot CLI** (`api.github.com/copilot_internal/v2/token` with `gh auth token` / `hosts.json` + `COPILOT_TOKEN`), and **Aider / OpenRouter** (`openrouter.ai/api/v1/auth/key` with `OPENROUTER_API_KEY`).
  - Full General Availability with proactive auth health guard integration and zero-dependency fallbacks.
  - Full Tri-Engine Parity across modular Python package, standalone runner (`agents.py`), and pure native PowerShell (`agents_native.ps1`).

### Feature 9: Local SQLite Historical Analytics & Burn-Down Charts (`--analytics`) [DELIVERED - v1.2.0]
- **Tracking Issue**: [#23](https://github.com/joseamair/agent-quota-tracker/issues/23)
- **Command**: `agents --analytics`, `agents --insights`, `agents analytics [--days N]`
- **Architecture**:
  - Embedded SQLite timeseries database under `~/.agent_quota_tracker/history.db` storing quota snapshots and verified poke records.
  - Zero-bloat deduplication skipping identical metrics recorded within 60 seconds.
  - Peak-hour analysis calculating top 3 usage hours and recommending optimal morning priming times (e.g., priming 90m prior to align 5h rolling resets with afternoon focus blocks).
  - Interactive Web Dashboard SVG 7-day velocity burn-down chart, 24-hour diurnal distribution, and summary cards.
  - Full Tri-Engine Parity across modular Python package (`src/agent_quota_tracker/history.py`), standalone runner (`agents.py`), and native PowerShell (`agents_native.ps1 -Analytics`).

### Feature 10: Proactive Token Expiration & Auth Health Guard [DELIVERED - v1.3.0]
- **Tracking Issue**: [#46](https://github.com/joseamair/agent-quota-tracker/issues/46)
- **Architecture**:
  - Local pre-flight inspection of OAuth credential caches (`~/.ccs/instances/<profile>/.credentials.json`, `~/.claude/`, Copilot internal tokens) reading `expiresAt` epoch millisecond timestamps before making external network calls.
  - Automatic detection and graceful interception of HTTP 401/403 responses across all provider APIs.
  - Prominent visual indicators: bold red `⚠️ EXPIRED` and bold yellow `⚠️ NO AUTH` with `Re-auth` / `Login req` status labels across all CLI tables and Web Dashboard cards.
  - Dedicated `🔐 Authentication Health Alerts` remediation panel with exact terminal commands to restore authentication (`ccs <profile> login`, `claude login`, `gh auth login`).
  - Safe skip guard preventing automated poke routines (`--poke`, `--auto`, `--poke-watch`, `--poke-at`) from dispatching prompts to expired accounts without `--force`.
  - Zero third-party dependencies; full Tri-Engine Parity across modular Python package, standalone runner (`agents.py`), and pure native PowerShell (`agents_native.ps1`).

### Feature 11: Prometheus Metrics Endpoint & Timeseries CSV Export [DELIVERED - v1.3.0]
- **Tracking Issue**: [#48](https://github.com/joseamair/agent-quota-tracker/issues/48)
- **Command**: `agents --metrics`, `agents metrics`, `agents export --csv`, `agents export --csv --type pokes --days 14`
- **Architecture**:
  - Live Prometheus 0.0.4 text format metrics exporter exposing 7 gauge metrics (`agent_quota_tracker_up`, `agent_quota_used_percent`, `agent_weekly_used_percent`, `agent_quota_remaining_fraction`, `agent_time_remaining_seconds`, `agent_is_active`, `agent_auth_valid`) with clean escaping and rich labels (`id`, `name`, `provider`, `category`).
  - Served directly at `GET /metrics` on the embedded Web Dashboard server (`localhost:5050/metrics`) and via `agents --metrics` CLI command.
  - Timeseries CSV export engine querying local SQLite database (`~/.agent_quota_tracker/history.db`) with date-range (`--days N`) and agent filtering (`--agent <id>`).
  - Web Dashboard integration with quick-access "📥 Export CSV" and "📈 Metrics" toolbar buttons and `GET /api/export` attachment route.
  - Zero third-party dependencies; full Tri-Engine Parity across modular Python package (`src/agent_quota_tracker/metrics.py`, `history.py`), standalone runner (`agents.py`), and pure native PowerShell (`agents_native.ps1 -Metrics`, `-ExportCsv`).

### Feature 12: Interactive Full-Screen Terminal TUI (`agents tui`) [DELIVERED - v1.3.0]
- **Tracking Issues**: [#50](https://github.com/joseamair/agent-quota-tracker/issues/50), [#55](https://github.com/joseamair/agent-quota-tracker/issues/55)
- **Command**: `agents tui`, `agents --tui`
- **Architecture**:
  - Full-screen keyboard-driven terminal dashboard rendered in the terminal alternate screen buffer (`\033[?1049h`), restoring previous scrollback and cursor visibility upon exit.
  - Interactive row navigation (`↑`/`k` and `↓`/`j`), single-account poke (`p`), force poke (`f`), poke-all (`a`), manual API refresh (`r`), and floating help reference modal (`?`/`h`).
  - **Interactive Quick Filter Mode (`/`)**: Real-time interactive search prompt filtering accounts by name, provider, id, category, or semantic keywords (`idle`, `active`, `expired`), with `Backspace` and `Esc` to clear.
  - Real-time panels: Header statistics bar, interactive accounts table with live ticking second-by-second countdowns and Unicode progress bars, selected account metadata and auth remediation inspector panel, and activity status bar.
  - Zero-dependency non-blocking cross-platform input engine using `msvcrt` on Windows and `select`/`termios` on Linux/macOS.
  - Full Tri-Engine Parity across modular Python package (`src/agent_quota_tracker/tui.py`), standalone runner (`agents.py`), and native PowerShell (`agents_native.ps1 -Tui`).

---

## 6. Security & Isolation Principles

- **Zero Credential Transmission**: Tokens are read locally from standard credential paths (`~/.ccs/`, `~/.claude.json`, `~/.codex/`).
- **Strict HTTPS Boundaries**: Network traffic is strictly confined to official provider endpoints (`api.anthropic.com`).
- **No Third-Party Telemetry**: Quota tracking and status calculations run 100% locally.

---

## 7. Incoming Agent Handoff & Implementation Guide

For technical architecture details, strict git identity rules (`joseamair`), test verification procedures, and the active task board for incoming AI coding agents, see [HANDOFF.md](HANDOFF.md).
