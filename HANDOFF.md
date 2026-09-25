# 🤝 Agent Handoff Document & Engineering Context

Welcome, incoming AI Coding Agent! This document gives you immediate, end-to-end technical context to pick up work smoothly on `agent-quota-tracker` with zero friction.

---

## 📌 Executive Summary

- **Repository**: [`agent-quota-tracker`](https://github.com/joseamair/agent-quota-tracker)
- **Current Version**: `v1.1.0` (Released 2026-09-25)
- **Repository Visibility**: Public GitHub Template repository
- **Primary Goal**: High-performance local CLI monitor, autonomous watchdog daemon, and glassmorphism web dashboard tracking 5-hour rolling threshold windows and weekly quotas across AI coding agents (Claude via CCS & official CLI, OpenAI Codex, and Google Antigravity).

---

## 🔒 Mandatory Identity & Authentication Rules

> [!CAUTION]
> **STRICT USER IDENTITY CONSTRAINTS**:
> 1. **Git Author Identity**: You MUST exclusively commit as:
>    - Name: `joseamair`
>    - Email: `joseamair@gmail.com`
>    - **NEVER** use, commit as, or reference `joseamairkdra`.
> 2. **GitHub CLI Authentication**:
>    - Always ensure `joseamair` is the active GitHub CLI token before executing any `gh` commands:
>      ```powershell
>      $env:GH_TOKEN = (gh auth token --user joseamair)
>      ```
> 3. **Git Push Protocol**:
>    - Direct git pushes must include the basic authentication header with `joseamair`'s token:
>      ```powershell
>      $token = (gh auth token --user joseamair)
>      $b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$token"))
>      git -c http.extraheader="Authorization: Basic $b64" push origin <branch>
>      ```

---

## 🏗️ Architecture & Tri-Engine Parity Rule

The project is structured with a **Tri-Engine Runtime**. Whenever adding new CLI options, calculations, or features, **you MUST maintain parity across all three engines**:

```text
                                  ┌───────────────────────────┐
                                  │   agent-quota-tracker     │
                                  └─────────────┬─────────────┘
                                                │
             ┌──────────────────────────────────┼──────────────────────────────────┐
             ▼                                  ▼                                  ▼
 ┌───────────────────────┐          ┌───────────────────────┐          ┌───────────────────────┐
 │ Modular Python Pkg    │          │ Standalone Script     │          │ Native PowerShell     │
 │ src/agent_quota_tracker/│         │ agents.py             │          │ agents_native.ps1     │
 └───────────────────────┘          └───────────────────────┘          └───────────────────────┘
```

1. **Modular Python Package** (`src/agent_quota_tracker/`):
   - Entry point: [`cli.py`](src/agent_quota_tracker/cli.py) (`agents` command)
   - Base tracker & duration parsing: [`trackers/base.py`](src/agent_quota_tracker/trackers/base.py)
   - Agent trackers: [`trackers/claude.py`](src/agent_quota_tracker/trackers/claude.py), [`codex.py`](src/agent_quota_tracker/trackers/codex.py), [`agy.py`](src/agent_quota_tracker/trackers/agy.py)
   - Configuration loader: [`config.py`](src/agent_quota_tracker/config.py)
   - Data models: [`models.py`](src/agent_quota_tracker/models.py)
   - Web server: [`server.py`](src/agent_quota_tracker/server.py)
2. **Standalone Python Runner** ([`agents.py`](agents.py)):
   - Single-file zero-dependency runner capable of running directly via `python agents.py`.
   - Mirrors all logic from `src/agent_quota_tracker/`.
3. **Pure Native PowerShell** ([`agents_native.ps1`](agents_native.ps1)):
   - Complete PowerShell implementation for environments where Python is unavailable.
   - Implements native REST queries, CLI parsing, table formatting, and watchdog loops.
4. **Platform Launchers**:
   - Windows PowerShell wrapper: [`agents.ps1`](agents.ps1)
   - Windows Command Prompt: [`agents.cmd`](agents.cmd)
   - Linux & macOS POSIX Bash: [`agents.sh`](agents.sh)

---

## 🧪 Verification & Testing Commands

Before pushing any commit or opening a PR, always execute the automated test suites:

```powershell
# 1. Run Python unit tests (must pass 38/38)
uv run pytest -v

# 2. Syntax check standalone script
uv run python -m py_compile agents.py

# 3. CLI help check
uv run agents --help

# 4. PowerShell AST syntax parser validation
$errors = @(); $tokens = $null;
$ast1 = [System.Management.Automation.Language.Parser]::ParseFile("agents.ps1", [ref]$tokens, [ref]$errors);
if ($errors.Count -gt 0) { throw $errors[0].Message }
$ast2 = [System.Management.Automation.Language.Parser]::ParseFile("agents_native.ps1", [ref]$tokens, [ref]$errors);
if ($errors.Count -gt 0) { throw $errors[0].Message }
Write-Host "All PowerShell scripts validate cleanly!"
```

---

## 📋 Active Roadmap Issues Ready for Implementation

The following 6 issues are currently open on GitHub and scheduled for **v1.2.0 & Beyond**:

| Issue | Title | Complexity | Suggested Approach |
|---|---|---|---|
| [**#20**](https://github.com/joseamair/agent-quota-tracker/issues/20) | **Native Desktop Toast Notifications & System Tray Indicator** | Medium | Integrate native OS toast alerts via PowerShell `New-BurntToastNotification` / WinRT on Windows, `notify-send` on Linux, and `osascript` on macOS. Optional tray icon using `pystray`. |
| [**#21**](https://github.com/joseamair/agent-quota-tracker/issues/21) | **Additional Agent Trackers (Cursor, Windsurf, Copilot, Aider)** | Medium | Add tracker classes under `src/agent_quota_tracker/trackers/` implementing `AgentTracker`. Extract fast requests from Cursor SQLite/tokens and Windsurf config. |
| [**#22**](https://github.com/joseamair/agent-quota-tracker/issues/22) | **OS-Level Automated Priming Task Generator (`--schedule-install`)** | Medium | Implement CLI commands `--schedule-install`, `--schedule-status`, `--schedule-remove` via Windows Task Scheduler (`schtasks.exe`), systemd-timer, or launchd. |
| [**#23**](https://github.com/joseamair/agent-quota-tracker/issues/23) | **Local SQLite Historical Analytics & Burndown Charts** | Medium | Add SQLite database at `~/.agent_quota_tracker/history.db` logging quota events. Add `agents --analytics` and embedded SVG chart in `dashboard.html`. |
| [**#24**](https://github.com/joseamair/agent-quota-tracker/issues/24) | **Web Dashboard v2 (Live Push & Interactive Controls)** | Medium | Add Server-Sent Events (SSE) route `/api/stream` to `server.py`. Add per-card poke buttons and theme switcher (Dark, Cyberpunk OLED, Light) to `dashboard.html`. |
| [**#25**](https://github.com/joseamair/agent-quota-tracker/issues/25) | **Shell Prompt & Status Bar Integration (`--prompt-format`)** | Low / Quick Win | Add sub-10ms cached status segment reader `agents --prompt-format` for Starship, Oh-My-Posh, and tmux. |

---

## ⚙️ User Setup Context

- **Working Directory**: `D:\wsl_files\personal_projects\agents_dashboard`
- **Shell**: PowerShell 7 (`pwsh`) on Windows 11
- **Tracked Accounts (5 accounts)**:
  1. `agy` (Google Antigravity)
  2. `codex` (OpenAI Codex)
  3. `personal` (Claude Personal via CCS)
  4. `work` (Claude Work via CCS)
  5. `work2` (Claude Work2 via CCS)
- **Configuration File**: [`agents.config.json`](agents.config.json)

---

## 🚀 Workflow for Implementing a Feature

1. **Pick an issue**: Check open issues via `gh issue list`.
2. **Create feature branch**:
   ```bash
   git checkout -b feat/issue-<number>-<short-description>
   ```
3. **Implement changes**:
   - Update `src/agent_quota_tracker/`
   - Update `agents.py`
   - Update `agents_native.ps1`
4. **Add unit tests**: Add test cases to `tests/`.
5. **Run test verification**: Ensure all 38+ pytest tests and PowerShell parser checks pass.
6. **Update docs**: Update `README.md` and `CHANGELOG.md` under `[Unreleased]`.
7. **Commit & Push**:
   - Use `joseamair` credentials.
   - Reference the issue number in the commit message (e.g. `feat: implement desktop toast notifications (#20)`).
8. **Create Pull Request**:
   ```powershell
   $env:GH_TOKEN = (gh auth token --user joseamair)
   gh pr create --title "..." --body "Closes #..."
   ```
