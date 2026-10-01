# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [Unreleased]

### Fixed
- **Accurate 5-Hour Idle Threshold (Sliding Window Ceiling Fix)** ([#29](https://github.com/joseamair/agent-quota-tracker/issues/29)):
  - Fixed false-inactive bug in `ClaudeTracker` and `AGYTracker` where accounts with `0.0%` token utilization were unconditionally treated as `○ INACTIVE / Ready to Poke`, even when counting down inside an active window with remaining time (e.g. 18 minutes left).
  - Implemented sliding prospective window ceiling check: an account with `0.0%` usage and no fresh poke is only considered idle if its reset time is at the sliding ceiling ($\ge 4\text{h } 59.25\text{m}$). Any countdown below that threshold is recognized as `● ACTIVE`.
  - Prevents premature, wasteful poke invocations on accounts approaching their natural reset window.

### Added
- **Autonomous Continuous Quota Auto-Checker Loop (`agents auto`, `--auto`, `--auto-poke`)** ([#31](https://github.com/joseamair/agent-quota-tracker/issues/31)):
  - Continuous autonomous monitoring and priming task that:
    1. Displays the live quota status table (`agents --status`).
    2. Immediately primes any currently idle accounts ready to poke (skipping $\ge 100\%$ weekly exhausted accounts unless `--force`).
    3. Calculates the earliest active 5-hour window reset time and displays a live ticking countdown: `⏳ Next poke target at <HH:MM:SS> (<Agent Name> (<time> left)) • Press Ctrl+C to stop`.
    4. Automatically primes newly available quota windows when the countdown completes and repeats in an infinite loop.
  - Zero-maintenance terminal daemon with clean `Ctrl+C` interrupt handling and zero orphaned background processes.
  - Full Tri-Engine Parity across modular Python package (`run_auto_checker_loop`), standalone runner (`agents.py`), and pure native PowerShell (`agents_native.ps1 -Auto`).

- **Weekly Quota Exhaustion Guard & Visual Alert System** ([#29](https://github.com/joseamair/agent-quota-tracker/issues/29)):
  - **Dynamic CLI Highlighting**: Weekly usage is now highlighted in `bold red` with `⚠️ 100%` when $\ge 100\%$, `bold red` when $\ge 90\%$, and `bold yellow` when $\ge 75\%$.
  - **Smart Poke Safety Guard**: `agents --poke`, `--poke-watch`, and OS scheduled priming tasks automatically skip accounts whose weekly quota has reached $\ge 100\%$ (or report provider `locked_reason`), saving residual token buffers from being wasted on greeting prompts.
  - Added `--force` (`-f`) override to allow explicitly bypassing the weekly exhaustion guard when desired.
  - Full Tri-Engine Parity across modular Python package, standalone `agents.py`, and pure native PowerShell (`agents_native.ps1`).

- **OS-Level Scheduled Morning Priming Task Generator (`--schedule-install`, `--schedule-status`, `--schedule-remove`)** ([#22](https://github.com/joseamair/agent-quota-tracker/issues/22)):
  - Built-in CLI commands to install, inspect status of, and remove unattended OS-level background scheduled morning priming tasks without third-party dependencies.
  - Cross-platform native scheduler support:
    - **Windows**: Windows Task Scheduler (`ScheduledTasks` cmdlets) operating safely in user space without requiring administrator elevation.
    - **Linux**: User `crontab` (`crontab -l` / `crontab -`).
    - **macOS**: `launchd` LaunchAgent plist (`~/Library/LaunchAgents/com.agentquotatracker.priming.plist`).
  - Persistent run logging to `~/.agent_quota_tracker/schedule.log` capturing timestamped installations, poke execution outcomes, and removals.
  - Positional subcommands supported (`agents schedule install [HH:MM]`, `agents schedule status`, `agents schedule remove`).
  - Complete Tri-Engine Parity across modular Python package (`src/agent_quota_tracker/scheduler.py`), standalone runner (`agents.py`), and pure PowerShell (`agents_native.ps1`).
- **Native Cross-Platform Desktop Toast Notifications (`--notify`, `-n`, `--test-notify`)** ([#20](https://github.com/joseamair/agent-quota-tracker/issues/20)):
  - Cross-platform desktop toast notifications dispatching system alerts upon successful agent priming (`--poke`), automated watchdog cooldown expirations (`--poke-watch`), and target-time schedule wakeups (`--poke-at`).
  - Zero third-party dependencies: uses native Windows 10/11 WinRT notifications via background PowerShell, macOS `osascript` notifications, and Linux `notify-send` with graceful fallback handling.
  - Added `--test-notify` diagnostic flag to immediately verify native notification pipeline functionality.
  - Added comprehensive test suite in `tests/test_notifications.py` covering Windows, macOS, and Linux dispatchers, special character sanitization, and error handling.
  - Full Tri-Engine Parity implemented across modular Python package (`src/agent_quota_tracker/notifications.py`), standalone runner (`agents.py`), and native PowerShell (`agents_native.ps1`).
- **Shell Prompt & Status Bar Integration (`--prompt`, `--prompt-format`)** ([#25](https://github.com/joseamair/agent-quota-tracker/issues/25)):
  - Ultra-fast (<15ms) cached status segments for Starship prompt, Oh-My-Posh, tmux status lines, and PowerShell `$PROFILE`.
  - Built-in presets: `default` (`[⚡ 3/5 Active • 2h14m]`), `compact` (`⚡3/5 2h14m`), `minimal` (`🤖 3/5`), `tmux`, and `json`.
  - Custom format templates supporting `{active}`, `{total}`, `{min_remaining}`, `{max_remaining}`, `{status}`, `{icon}`, and `{percent}` tokens.
  - Mathematical dynamic countdown engine: calculates active counts and remaining time second-by-second directly from cached timestamps without background CPU churn or API calls.
  - Zero-overhead disk cache residing under `~/.agent_quota_tracker/cache.json`, automatically refreshed on quota queries, pokes, and watch loops.
  - Full Tri-Engine Parity across modular Python package (`src/agent_quota_tracker/prompt.py`, `cache.py`), standalone runner (`agents.py`), and pure native PowerShell (`agents_native.ps1`).

## [1.1.0] - 2026-09-25

### Added
- **Automated Poke Watchdog Mode (`--poke-watch`)** ([#18](https://github.com/joseamair/agent-quota-tracker/issues/18)):
  - Continuous autonomous monitoring daemon that inspects 5-hour rolling windows and primes idle accounts automatically.
  - Configurable polling interval via `--interval <duration>` (e.g. `15m`, `30m`, `2h`, `7200s`).
  - **Adaptive Sleep Engine**: When no fixed interval is specified (or set to `auto`), dynamically sleeps until the earliest expiring active window plus safety margin (`min(remaining) + 45s`), eliminating CPU waste and API query spam.
  - Live single-line terminal countdown timer with clean `Ctrl+C` interrupt handling and zero orphaned background processes.
- **Scheduled Target-Time Morning Priming (`--poke-at`)** ([#19](https://github.com/joseamair/agent-quota-tracker/issues/19)):
  - Executes a verified poke across idle agents at a scheduled 24-hour target time (`HH:MM`, e.g. `agents --poke-at 07:30`).
  - Automatic overnight rollover if the specified target time is earlier in the day than current time.
  - Strategic workday peak-quota maximization: primes windows early morning so full reset occurs during peak afternoon coding hours.
- **Terminal Status Report Timestamp** ([#15](https://github.com/joseamair/agent-quota-tracker/issues/15)):
  - Displays the exact local time the quota check was executed in the status table header.
- **Official Claude Single-Account Support**:
  - Out-of-the-box fallback to standard Anthropic Claude CLI (`~/.claude/.credentials.json`, `~/.claude.json`, and direct `claude -p` invocation) when Claude Code Switcher (CCS) is not installed or profile is `"default"`.
- **Tri-Engine Parity**:
  - Implemented `--poke-watch`, `--poke-at`, and `--interval` across the modular Python package, standalone single-file `agents.py`, and pure PowerShell `agents_native.ps1`.

### Fixed
- **Google Antigravity & OpenAI Codex Idle False Positives** ([#16](https://github.com/joseamair/agent-quota-tracker/issues/16)):
  - Resolved false-positive active status on Codex and Antigravity when accounts are idle with 0% usage and sliding future reset timestamps.

---

## [1.0.0] - 2026-09-24

### Added
- **Multi-Account 5-Hour Rolling Threshold Monitoring**:
  - Live status tracking across Claude Work, Personal, Work2 (via CCS), OpenAI Codex, and Google Antigravity (AGY).
  - Terminal status table displaying active/inactive state, time remaining countdown, next reset time, 5h % usage, and weekly reset dates.
- **7-Day Weekly Quota & Reset Date Calculations**:
  - Calculates remaining hours until weekly reset.
  - Converts UTC reset timestamps to readable local date and time format (e.g. `in 64.3h (Sun Sep 27, 12:59)`).
- **Verified Smart Poke Engine (`--poke`)**:
  - Automatically skips active agents to prevent wasting quota tokens.
  - Dispatches non-interactive prompts (`"Hello, how are you doing?"`) with `stdin=DEVNULL`.
  - Waits for model responses and extracts clean single-line reply snippets.
  - Queries provider APIs immediately after poking to verify live window activation.
  - Supports `--force` (`-f`) and `--agent` (`-a`) flags for testing or targeted poking.
- **Real-Time Web Dashboard (`--dashboard`)**:
  - Embedded HTTP server on `http://localhost:5050` with REST endpoints (`/api/status`, `/api/poke`).
  - Standalone responsive HTML dashboard (`dashboard.html`) featuring glassmorphism UI, circular SVG progress rings, live JavaScript countdown timers, and manual poke triggers.
- **Dual-Engine Runtime**:
  - Python package and standalone single-file runner (`agents.py`).
  - Pure PowerShell native alternative (`agents_native.ps1`) for systems without Python.
- **Global PowerShell Terminal Integration**:
  - One-line function integration with `$PROFILE` allowing `agents` commands to run from any directory.
