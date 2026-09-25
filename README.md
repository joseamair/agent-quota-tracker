# ⚡ Agent Quota Tracker & 5-Hour Threshold Window Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Managed by uv](https://img.shields.io/badge/Managed%20by-uv-DE5FE9.svg)](https://github.com/astral-sh/uv)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-0078D4.svg)](https://github.com/joseamair/agent-quota-tracker)
[![CI](https://github.com/joseamair/agent-quota-tracker/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)

A lightweight, local quota monitoring system and web dashboard designed for developers managing multiple AI coding accounts. It automatically tracks **5-hour rolling threshold windows**, calculates **7-day weekly reset dates**, and provides a **verified smart poke engine** to start inactive quota countdowns on demand.

---

## 📑 Table of Contents

- [Supported Accounts](#-supported-accounts)
- [Key Features](#-key-features)
- [Architecture Overview](#-architecture-overview)
- [Quick Start](#-quick-start)
- [Account Configuration](#-account-configuration)
- [CLI Command Reference](#-cli-command-reference)
  - [`agents --status`](#1-agents---status--s)
  - [`agents --poke`](#2-agents---poke--p)
  - [`agents --poke-watch`](#3-agents---poke-watch)
  - [`agents --poke-at`](#4-agents---poke-at)
  - [`agents --dashboard`](#5-agents---dashboard--d)
  - [`agents --status --json`](#6-agents---status---json)
  - [`agents --status --watch`](#7-agents---status---watch--w)
- [Global PowerShell Integration](#-global-powershell-integration)
- [Web Dashboard Preview](#-web-dashboard-preview)
- [Linux & macOS Compatibility & Setup Guide](#-linux--macos-compatibility--setup-guide)
- [Fork & Customize for Your Workflow](#-fork--customize-for-your-workflow)
- [Project Roadmap](#-project-roadmap)
- [Frequently Asked Questions (FAQ)](#-frequently-asked-questions-faq)
- [Security & Credential Privacy](#-security--credential-privacy)
- [Contributing](#-contributing)
- [Agent Handoff & Architecture Guide](HANDOFF.md)
- [Changelog](#-changelog)
- [License](#-license)

---

## 🤖 Supported Accounts

| Account | Provider | CLI / Integration | Quota Engine |
|---|---|---|---|
| **Google Antigravity** | Google | `agy` CLI | Direct live quota (`agy -p "/usage" --output-format json`) |
| **OpenAI Codex** | OpenAI | `codex` CLI | Real-time JSON-RPC (`account/rateLimits/read`) |
| **Claude (Multi-Account)** | Anthropic | CCS profile (`~/.ccs/instances/`) | Instant live OAuth Usage API (`api.anthropic.com`) |
| **Claude (Standard CLI)** | Anthropic | Official `claude` (`~/.claude/`) | Direct OAuth Usage API with fallback to `claude -p` |

> 💡 **Claude Multi-Account vs Single-Account Setup**:
> - **Multi-Account (`ccs`)**: By default, this dashboard tracks 3 distinct Claude profiles (`personal`, `work`, `work2`) using the [Claude Code Switcher (`ccs`)](https://github.com/joseamair/ccs) tool. Each profile keeps its own tokens in `~/.ccs/instances/<profile>`.
> - **Standard Claude CLI**: If you don't use `ccs` and only have a single official Anthropic Claude installation (Windows, macOS, or Linux), the tracker seamlessly supports it out of the box! It reads credentials directly from `~/.claude/.credentials.json` (or `~/.claude.json`) and pokes using `claude -p` directly. Simply set `"profile": "default"` or omit the profile in `agents.config.json`.
>
> 📖 **Deep Dive**: For full technical details on agent quota mechanics, sliding window heuristics, and peak-time priming strategies, see [AGENTS.md](AGENTS.md). For engineering guidelines, identity constraints, and context for incoming AI coding assistants, see [HANDOFF.md](HANDOFF.md).

---

## 🌟 Key Features

- **5-Hour Rolling Window Monitoring**: Displays live `● ACTIVE` vs `○ INACTIVE` states, exact time remaining countdowns (`Xh Ym Zs`), 5h % usage, and report check timestamps.
- **Weekly Reset Timestamps**: Calculates hours remaining until weekly quota resets, converting timestamps into local readable dates (e.g., `in 64.3h (Sun Sep 27, 12:59)`).
- **Verified Smart Poke Engine**:
  - Automatically skips active agents to prevent wasting quota tokens.
  - Sends a light prompt (`"Hello, how are you doing?"`) with non-interactive standard input (`stdin=DEVNULL`).
  - **Waits for the model to reply**, extracts a clean response snippet, and immediately re-queries provider APIs to verify live window activation.
  - Supports `--force` (`-f`) and `--agent` (`-a`) flags.
- **Automated Poke Watchdog (`--poke-watch`)**:
  - Continuous autonomous monitoring daemon that inspects 5-hour rolling windows and primes idle accounts automatically.
  - **Adaptive Sleep Engine**: Computes dynamic sleep duration based on earliest expiring active window (`min(remaining) + 45s`), eliminating CPU churn and API spam.
  - Supports fixed intervals (`--interval 30m`, `2h`, `7200s`).
- **Scheduled Target-Time Morning Priming (`--poke-at`)**:
  - Automatically primes 5-hour rolling threshold windows at a planned target time (`HH:MM`, e.g. `07:30`).
  - Automatically rolls over to the next morning if the target time has passed today.
  - Maximizes workday coding output: primes early so you receive a fresh 100% quota reset right in the middle of afternoon peak hours.
- **Interactive Web Dashboard**:
  - Embedded HTTP server at `http://localhost:5050` with REST endpoints (`/api/status`, `/api/poke`).
  - Circular SVG progress rings, live ticking JavaScript countdown timers, and manual poke triggers.
- **Tri-Engine Implementation**:
  - Full Python package with Rich terminal formatting (`uv run agents` or `python -m agent_quota_tracker`).
  - Standalone single-file Python runner (`agents.py`).
  - Pure PowerShell native script (`agents_native.ps1`) for systems without Python.

---

## 🏗️ Architecture Overview

```text
                  ┌────────────────────────────────────────┐
                  │          agents CLI / Dashboard        │
                  │   (--status, --poke, --dashboard)      │
                  └──────────────────┬─────────────────────┘
                                     │
           ┌─────────────────────────┼─────────────────────────┐
           ▼                         ▼                         ▼
   ┌───────────────┐         ┌───────────────┐         ┌───────────────┐
   │ Claude (CCS)  │         │ OpenAI Codex  │         │ Google AGY    │
   │ 3 Profiles    │         │ Background RPC│         │ /usage Command│
   └───────┬───────┘         └───────┬───────┘         └───────┬───────┘
           │                         │                         │
           ▼                         ▼                         ▼
   Anthropic OAuth API       codex app-server        agy CLI /usage            
   api.anthropic.com         rateLimits/read         JSON Quota Output
```

---

## ⚡ Quick Start

### Prerequisites
- Windows 10/11 with PowerShell (`pwsh`)
- Python 3.11+ managed by [uv](https://github.com/astral-sh/uv)
- Installed CLIs: `agy` (Antigravity), `codex` (OpenAI), and `ccs` (Claude Code Switcher for multi-account) OR official `claude` (for single-account)

### Installation

1. Clone or download this repository:
   ```bash
   git clone https://github.com/joseamair/agent-quota-tracker.git
   cd agent-quota-tracker
   ```

2. Sync dependencies:
   ```bash
   uv sync
   ```

3. Run commands right away:
   ```powershell
   .\agents.ps1 --status
   ```

---

## 🎯 CLI Command Reference

### 1. `agents --status` (`-s`)
Displays a formatted status table across all accounts:

```powershell
.\agents.ps1 --status
# Or with native PowerShell:
.\agents_native.ps1 -Status
```

**Sample Output:**
```text
================================================================================================================================
  ⚡ AI AGENTS 5-HOUR & WEEKLY WINDOW QUOTA STATUS
================================================================================================================================
Agent / Account          Provider  5h State    5h Left      Next 5h Reset      5h Use   Wk Use   Weekly Reset (Hours & Date)     
--------------------------------------------------------------------------------------------------------------------------------
Google Antigravity (AGY) AGY       ● ACTIVE    4h 07m 51s   03:44:28 (Today)   30.5%    20.6%    in 129.2h (Wed Sep 30, 08:47)   
OpenAI Codex             Codex     ● ACTIVE    1h 47m 02s   01:23:40 (Today)   50.0%    71.0%    in 82.5h (Mon Sep 28, 10:07)    
Claude (Personal)        Claude    ● ACTIVE    1h 43m 22s   01:20:00 (Today)   0.0%     74.0%    in 96.4h (Tue Sep 29, 00:00)    
Claude (Work)            Claude    ● ACTIVE    1h 43m 21s   01:19:59 (Today)   28.0%    42.0%    in 61.4h (Sun Sep 27, 12:59)    
Claude (Work2)           Claude    ● ACTIVE    4h 33m 21s   04:10:00 (Today)   1.0%     53.0%    in 93.4h (Mon Sep 28, 21:00)    
================================================================================================================================
```

---

### 2. `agents --poke` (`-p`)
Inspects 5-hour rolling threshold windows. Inactive accounts are poked with a light prompt to initiate their window; active accounts are skipped automatically.

<p align="center">
  <img src="assets/screenshots/poke-cat.gif" alt="Poking the agent" width="260" />
  <br>
  <em>"Wake up, agent! Time to start the 5-hour quota window." — Gently waking up dormant accounts before peak coding hours.</em>
</p>

```powershell
# Poke all inactive accounts:
.\agents.ps1 --poke

# Force poke an account even if active (useful for testing):
.\agents.ps1 --poke --force --agent work

# With native PowerShell:
.\agents_native.ps1 -Poke -Force -TargetAgent codex
```

**Sample Output:**
```text
⚡ [POKE] Checking 5-hour rolling threshold windows (FORCE mode enabled)...

  ⏳ POKING:  Claude (Work)             Forcing poke. Sending prompt & waiting for reply...
  ✔ SUCCESS: Claude (Work)             Verified ACTIVE (4h 42m 40s remaining, 5.0% used)
             ↳ Reply: "Doing well, thanks! I'm ready to work on your agents dashboard project."

Done!
```

---

### 3. `agents --poke-watch`
Continuous autonomous watchdog daemon that monitors agent 5-hour quota windows and automatically primes accounts the moment they become idle.

```powershell
# Adaptive Mode (Default): sleeps until earliest expiring window (+45s safety margin)
.\agents.ps1 --poke-watch

# Fixed Polling Interval (e.g. check every 30 minutes or 2 hours):
.\agents.ps1 --poke-watch --interval 30m
.\agents.ps1 --poke-watch --interval 2h

# With native PowerShell:
.\agents_native.ps1 -PokeWatch -Interval 30m
```

> 🧠 **Adaptive Sleep Engine**:  
> In adaptive mode (default), the daemon queries active accounts once, finds the earliest expiring 5-hour window, and sleeps for exactly that remaining duration plus a 45-second margin. It runs a live single-line terminal countdown timer (`⏳ Next check in: 1h 42m 15s remaining • Press Ctrl+C to cancel`), avoiding API query spam and CPU churn while guaranteeing instant priming when an account turns idle.

---

### 4. `agents --poke-at HH:MM`
Schedules an automated poke at a specific planned time of day (24-hour format) to prime accounts before your deep work starts.

```powershell
# Prime accounts tomorrow morning at 07:30 AM:
.\agents.ps1 --poke-at 07:30

# With native PowerShell:
.\agents_native.ps1 -PokeAt 07:30
```

> 🎯 **Workday Double-Quota Strategy**:  
> If you start work at 09:00 AM and run a manual query, your 5-hour window runs until 02:00 PM. If you hit your quota by 12:00 PM, you're locked out until 02:00 PM.  
> By scheduling `agents --poke-at 07:30`, Window 1 starts early while you're offline. When you log in at 09:00 AM, you have full quota. At 12:30 PM (lunchtime / start of afternoon focus), **Window 1 resets back to 100%**, providing a full fresh allocation for the entire afternoon!  
> *(If the target time has already passed today, the tracker automatically rolls over to the next morning).*

---

### 5. `agents --dashboard` (`-d`)
Spins up the local web dashboard at `http://localhost:5050` and automatically opens it in your default browser.

```powershell
.\agents.ps1 --dashboard
# Or with native PowerShell:
.\agents_native.ps1 -Dashboard
```

> **💡 Quick 1-Click Desktop Launcher**:  
> Double-click `start-dashboard.cmd` directly from Windows Explorer or your desktop to start the dashboard server and open your browser instantly!

---

### 6. `agents --status --json`
Outputs raw machine-readable JSON status for all tracked accounts (ideal for custom status bars, polybars, tmux, and automation):

```powershell
.\agents.ps1 --status --json
# Or with uv:
uv run agents --json
```

**Sample Output:**
```json
[
  {
    "id": "agy",
    "name": "Google Antigravity (AGY)",
    "provider": "AGY",
    "category": "personal",
    "is_active": true,
    "used_percent": 47.9,
    "time_remaining_str": "3h 34m 10s",
    "weekly_used_percent": 23.8,
    "weekly_reset_str": "in 128.6h (Wed Sep 30, 08:47)"
  }
]
```

---

### 7. `agents --status --watch` (`-w`)
Continuously refreshes the quota status table in your terminal every N seconds (default: 15s) with a clear screen:

```powershell
# Refresh every 15 seconds:
.\agents.ps1 --status --watch

# Custom interval (e.g. 30 seconds):
.\agents.ps1 --watch 30
```

---

## ⚙️ Account Configuration

Tracked accounts and display order are configured in `agents.config.json` (or `~/.agents_dashboard/config.json`). By default, personal accounts are grouped at the top, followed by work accounts:

```json
{
  "accounts": [
    { "id": "agy", "provider": "agy", "name": "Google Antigravity (AGY)", "category": "personal", "enabled": true },
    { "id": "codex", "provider": "codex", "name": "OpenAI Codex", "category": "personal", "enabled": true },
    { "id": "personal", "provider": "claude", "profile": "personal", "name": "Claude (Personal)", "category": "personal", "enabled": true },
    { "id": "work", "provider": "claude", "profile": "work", "name": "Claude (Work)", "category": "work", "enabled": true },
    { "id": "work2", "provider": "claude", "profile": "work2", "name": "Claude (Work2)", "category": "work", "enabled": true }
  ]
}
```

You can customize names, disable specific agents (`"enabled": false`), or adjust order by editing `agents.config.json` (template provided in `agents.config.example.json`).

---

## 🌐 Global PowerShell Integration

To make `agents` available from **any folder** in PowerShell without typing paths, add this 3-line function to your PowerShell profile (`C:\Users\<user>\Documents\PowerShell\Microsoft.PowerShell_profile.ps1`):

```powershell
# AI Agents 5-Hour Quota Tracker & Dashboard
function agents {
    & "$HOME\path\to\agent-quota-tracker\agents.ps1" @args
}
```

Now you can simply type:
```powershell
agents --status
agents --poke
agents --dashboard
```

---

## 🐧 Linux & 🍎 macOS Compatibility & Setup Guide

`agent-quota-tracker` is cross-platform and natively supported on **Ubuntu, Debian, Fedora, Arch Linux, and macOS**.

### 1. Running with POSIX Bash (`agents.sh`)

Make the script executable:
```bash
chmod +x agents.sh
./agents.sh --status
./agents.sh --poke
./agents.sh --dashboard
```

### 2. Global Shell Alias (`bash`, `zsh`, `fish`)

Add this alias to your shell profile (`~/.bashrc`, `~/.zshrc`, or `~/.config/fish/config.fish`):

```bash
# In ~/.bashrc or ~/.zshrc:
alias agents="$HOME/path/to/agent-quota-tracker/agents.sh"
```

Reload your profile (`source ~/.bashrc` or `source ~/.zshrc`) to run `agents` from any working directory!

### 3. Cross-Platform Path Mapping

Provider credentials and configurations are mapped automatically from your standard home directory:
- **Anthropic CCS**: `~/.ccs/instances/`
- **Claude CLI cache**: `~/.claude.json`
- **OpenAI Codex**: `~/.codex/`
- **Google Antigravity**: `~/.gemini/antigravity-cli/`
- **Quota Tracker Config**: `~/.agent_quota_tracker/config.json` (or local `agents.config.json`)

---

## 🍴 Fork & Customize for Your Workflow

`agent-quota-tracker` is built to be modular, hackable, and instantly extensible for your specific team or personal agent setups. 

[![Fork on GitHub](https://img.shields.io/badge/GitHub-Fork%20Repository-blue?logo=github&style=for-the-badge)](https://github.com/joseamair/agent-quota-tracker/fork)
[![Star on GitHub](https://img.shields.io/badge/GitHub-Star%20Repo-yellow?logo=github&style=for-the-badge)](https://github.com/joseamair/agent-quota-tracker)

### Why Fork This Repo?
- **Tailor Your Account Fleet**: Edit `agents.config.json` to monitor 1 account, 10 accounts, or cross-company setups across personal laptops, cloud workstations, or VPS instances.
- **Add New Agent Trackers**: Add plug-and-play trackers under [`src/agent_quota_tracker/trackers/`](src/agent_quota_tracker/trackers/) by implementing the base `AgentTracker` interface.
- **Hook Into Custom Pipelines**: Use `agents --status --json` to pipe real-time agent capacity into your custom polybars, tmux status lines, internal developer portals, or Slack/Discord webhooks.
- **Contributions Welcome**: Submit your improvements, new provider trackers, or custom UI themes as Pull Requests!

---

## 🗺️ Project Roadmap

### 🚀 Delivered in v1.1.0
- [x] **Automated Poke Watchdog Mode (`--poke-watch`)** ([#18](https://github.com/joseamair/agent-quota-tracker/issues/18)): Autonomous daemon with dynamic adaptive cooling engine based on earliest expiring active window.
- [x] **Scheduled Target-Time Poke (`--poke-at`)** ([#19](https://github.com/joseamair/agent-quota-tracker/issues/19)): Strategic morning priming with automatic overnight clock rollover.
- [x] **Terminal Status Report Timestamp** ([#15](https://github.com/joseamair/agent-quota-tracker/issues/15)): Explicit check timestamp displayed on the status table header.
- [x] **AGY & Codex False-Positive Quota Fixes** ([#16](https://github.com/joseamair/agent-quota-tracker/issues/16)): Strict idle window verification for sliding prospective timestamps.
- [x] **Official Claude CLI Support**: Native single-account discovery and fallback to official Anthropic `claude` CLI.

### 🔭 Active Development Roadmap (v1.2.0 & Beyond)
- [ ] **Native Desktop Toast Notifications & System Tray Indicator** ([#20](https://github.com/joseamair/agent-quota-tracker/issues/20)):
  Cross-platform desktop notifications (Windows Action Center, macOS, Linux `notify-send`) on 5h window cooldown, morning priming completion, and persistent tray status icon.
- [ ] **Additional AI Agent Trackers** ([#21](https://github.com/joseamair/agent-quota-tracker/issues/21)):
  Extend modular trackers to support Cursor (fast requests/billing reset), Windsurf/Cascade (credits), GitHub Copilot CLI (rate limits), and Aider/OpenRouter (balance).
- [ ] **OS-Level Automated Morning Priming (`--schedule-install`)** ([#22](https://github.com/joseamair/agent-quota-tracker/issues/22)):
  Native Windows Task Scheduler / Linux systemd / macOS launchd generator to execute morning priming persistently without keeping a terminal open.
- [ ] **Local SQLite Historical Analytics & Quota Velocity Charts** ([#23](https://github.com/joseamair/agent-quota-tracker/issues/23)):
  Embedded timeseries logging (`history.db`) to record burn rate patterns, peak usage hours, and 7-day burndown visualizations.
- [ ] **Web Dashboard v2 (Live Push & Interactive Controls)** ([#24](https://github.com/joseamair/agent-quota-tracker/issues/24)):
  Server-Sent Events (SSE) live push updates, per-agent poke buttons, in-browser target-time scheduler, and OLED/Dark/Light theme switcher.
- [ ] **Shell Prompt & Status Bar Integration (`--prompt-format`)** ([#25](https://github.com/joseamair/agent-quota-tracker/issues/25)):
  Ultra-fast sub-10ms cached status segments for Starship prompt, Oh-My-Posh, tmux status lines, and PowerShell `$PROFILE`.

---

## ❓ Frequently Asked Questions (FAQ)

<details>
<summary><b>Does poking consume expensive tokens or count as quota usage?</b></summary>
<br>
The poke engine sends a lightweight greeting prompt (<code>"Hello, how are you doing?"</code>) with <code>stdin=DEVNULL</code>. This triggers the provider's rolling 5-hour window countdown without running commands or consuming significant prompt tokens. Active windows are automatically skipped.
</details>

<details>
<summary><b>How are credentials protected?</b></summary>
<br>
All API calls are directed strictly to official provider endpoints (such as <code>https://api.anthropic.com/api/oauth/usage</code>). Tokens are read in local memory only and never written to logs, committed to Git, or sent to third-party telemetry.
</details>

<details>
<summary><b>Can I reorder or disable specific accounts?</b></summary>
<br>
Yes! Edit <code>agents.config.json</code> (or copy from <code>agents.config.example.json</code>). You can toggle <code>"enabled": false</code> or change the array ordering to your preference.
</details>


---

## 🔒 Security & Credential Privacy

This project is built following strict local security guidelines:
- **Zero External Telemetry**: Access tokens from `~/.ccs/instances/` and `~/.claude.json` are read exclusively in local memory.
- **Direct Official Endpoints**: Outbound requests are directed strictly to official API endpoints (`api.anthropic.com`).
- For detailed information, see [SECURITY.md](SECURITY.md).

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!  
Please read [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for details on code style, testing, and adding new AI agent trackers.

---

## 📝 Changelog

Detailed release notes and version history are maintained in [CHANGELOG.md](CHANGELOG.md).

---

## 📄 License

This project is open-source and licensed under the [MIT License](LICENSE).
