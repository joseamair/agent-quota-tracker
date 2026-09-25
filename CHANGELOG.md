# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
