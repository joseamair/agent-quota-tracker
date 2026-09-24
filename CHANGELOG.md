# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
