# ⚡ Agent Quota Tracker & 5-Hour Threshold Window Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![Managed by uv](https://img.shields.io/badge/Managed%20by-uv-DE5FE9.svg)](https://github.com/astral-sh/uv)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20PowerShell-0078D4.svg)](https://microsoft.com/powershell)
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
  - [`agents --dashboard`](#3-agents---dashboard--d)
- [Global PowerShell Integration](#-global-powershell-integration)
- [Web Dashboard Preview](#-web-dashboard-preview)
- [Security & Credential Privacy](#-security--credential-privacy)
- [Contributing](#-contributing)
- [Changelog](#-changelog)
- [License](#-license)

---

## 🤖 Supported Accounts

| Account | Provider | CLI / Integration | Quota Engine |
|---|---|---|---|
| **Google Antigravity** | Google | `agy` CLI | Direct live quota (`agy -p "/usage" --output-format json`) |
| **OpenAI Codex** | OpenAI | `codex` CLI | Real-time JSON-RPC (`account/rateLimits/read`) |
| **Claude (Personal)** | Anthropic | CCS profile `personal` | Instant live OAuth Usage API (`api.anthropic.com`) |
| **Claude (Work)** | Anthropic | CCS profile `work` | Instant live OAuth Usage API (`api.anthropic.com`) |
| **Claude (Work2)** | Anthropic | CCS profile `work2` | Instant live OAuth Usage API (`api.anthropic.com`) |

---

## 🌟 Key Features

- **5-Hour Rolling Window Monitoring**: Displays live `● ACTIVE` vs `○ INACTIVE` states, exact time remaining countdowns (`Xh Ym Zs`), and 5h % usage.
- **Weekly Reset Timestamps**: Calculates hours remaining until weekly quota resets, converting timestamps into local readable dates (e.g., `in 64.3h (Sun Sep 27, 12:59)`).
- **Verified Smart Poke Engine**:
  - Automatically skips active agents to prevent wasting quota tokens.
  - Sends a light prompt (`"Hello, how are you doing?"`) with non-interactive standard input (`stdin=DEVNULL`).
  - **Waits for the model to reply**, extracts a clean response snippet, and immediately re-queries provider APIs to verify live window activation.
  - Supports `--force` (`-f`) and `--agent` (`-a`) flags.
- **Interactive Web Dashboard**:
  - Embedded HTTP server at `http://localhost:5050` with REST endpoints (`/api/status`, `/api/poke`).
  - Circular SVG progress rings, live ticking JavaScript countdown timers, and manual poke triggers.
- **Dual-Engine Implementation**:
  - Full Python package with Rich terminal formatting (`uv run agents` or `python agents.py`).
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
- Installed CLIs: `ccs`, `codex`, `agy`

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

### 3. `agents --dashboard` (`-d`)
Spins up the local web dashboard at `http://localhost:5050` and automatically opens it in your default browser.

```powershell
.\agents.ps1 --dashboard
# Or with native PowerShell:
.\agents_native.ps1 -Dashboard
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
