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
2. **Lightweight Invocation**:
   - Anthropic Claude: Dispatches `ccs <profile> -p "Hello, how are you doing?"` (or `claude -p` for standard single-account setups) with `stdin=DEVNULL`.
   - OpenAI Codex: Dispatches non-interactive query via `codex exec`.
   - Google Antigravity: Dispatches non-interactive query via `agy prompt`.
3. **Response Verification**: Waits for the model to reply, extracts a single-line summary (e.g. `↳ Reply: "I am doing well, ready to help..."`), and instantly re-queries the provider usage API to confirm the 5-hour window is live.

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

To automate this strategy without manual terminal loops, the following features have been implemented and released in **v1.1.0**:

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

### Next Phase Capabilities (v1.2.0 & Beyond)
- **Desktop Toast Notifications & System Tray Applet** ([#20](https://github.com/joseamair/agent-quota-tracker/issues/20)): Native OS notification alerts on cooldown and morning priming with persistent tray status.
- **Additional Agent Trackers** ([#21](https://github.com/joseamair/agent-quota-tracker/issues/21)): Cursor Composer, Windsurf/Cascade, GitHub Copilot CLI, and Aider/OpenRouter.
- **OS-Level Scheduled Task Generator** ([#22](https://github.com/joseamair/agent-quota-tracker/issues/22)): `agents --schedule-install` via Windows Task Scheduler, systemd, and launchd.
- **Historical Timeseries & Velocity Analytics** ([#23](https://github.com/joseamair/agent-quota-tracker/issues/23)): Local SQLite database (`history.db`) tracking burn rates and 7-day burndown charts.
- **Web Dashboard v2** ([#24](https://github.com/joseamair/agent-quota-tracker/issues/24)): Server-Sent Events (SSE) live push updates, per-card controls, and OLED/Dark/Light themes.
- **Shell Prompt & Status Bar Integration** ([#25](https://github.com/joseamair/agent-quota-tracker/issues/25)): Fast cached prompt segments for Starship, Oh-My-Posh, tmux, and PowerShell.

---

## 6. Security & Isolation Principles

- **Zero Credential Transmission**: Tokens are read locally from standard credential paths (`~/.ccs/`, `~/.claude.json`, `~/.codex/`).
- **Strict HTTPS Boundaries**: Network traffic is strictly confined to official provider endpoints (`api.anthropic.com`).
- **No Third-Party Telemetry**: Quota tracking and status calculations run 100% locally.

---

## 7. Incoming Agent Handoff & Implementation Guide

For technical architecture details, strict git identity rules (`joseamair`), test verification procedures, and the active task board for incoming AI coding agents, see [HANDOFF.md](HANDOFF.md).
