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
# 1. Run Python unit tests (must pass 105/105)
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

All initial roadmap issues for **v1.2.0** have now been delivered across the Tri-Engine architecture! Future roadmap planning and issues will be curated for upcoming minor and major releases.

### Recently Delivered
- [**#23**](https://github.com/joseamair/agent-quota-tracker/issues/23) - **Local SQLite Historical Analytics & Burndown Charts**: Embedded SQLite timeseries database under `~/.agent_quota_tracker/history.db` storing quota snapshots and poke records with 60s deduplication. Added `agents --analytics`, `--insights`, and `agents analytics [--days N]` displaying active time ratio, top 3 peak hours, optimal morning priming recommendation, and 24-hour diurnal distribution. Embedded interactive SVG 7-day velocity burn-down chart, 24-hour activity bars, and period selector (24h, 3d, 7d, 14d) in Web Dashboard with `/api/history` and `/api/analytics` endpoints. Full Tri-Engine Parity.
- [**#21**](https://github.com/joseamair/agent-quota-tracker/issues/21) - **Additional Agent Trackers (Cursor, Windsurf, Copilot, Aider - Beta)**: Modular implementations for Cursor (SQLite token discovery + `api2.cursor.sh`), Windsurf (`~/.codeium/config.json` + `api.codeium.com`), GitHub Copilot (`gh auth token` + Copilot token API), and Aider (`OPENROUTER_API_KEY` + OpenRouter balance API). Open call for community validation. Full Tri-Engine Parity.
- [**#24**](https://github.com/joseamair/agent-quota-tracker/issues/24) - **Web Dashboard v2 (Live Push & Interactive Controls)**: Real-time Server-Sent Events (SSE) `/api/stream` streaming, per-card "⚡ Poke" / "⚡ Force Poke" buttons, interactive morning priming configuration modal (`/api/schedule`), 3 switchable themes (Dark, Cyberpunk OLED, Light), and live ticking JS countdowns. Full Tri-Engine Parity.
- [**#31**](https://github.com/joseamair/agent-quota-tracker/issues/31) - **Autonomous Continuous Auto-Checker Loop (`agents auto`, `--auto-poke`)**: Continuous autonomous monitoring and priming task that loops endlessly, priming idle accounts, computing the earliest reset time, and running a live single-line ticking countdown until next priming.
- [**#29**](https://github.com/joseamair/agent-quota-tracker/issues/29) - **Accurate 5-Hour Idle Threshold (Sliding Window Ceiling Fix) & Weekly Quota Guard**: Fixed false-inactive bug on 0% accounts with remaining window time, dynamic red/yellow weekly alerts, and poke guard skipping accounts with $\ge 100\%$ weekly usage.
- [**#22**](https://github.com/joseamair/agent-quota-tracker/issues/22) - **OS-Level Scheduled Priming Task Generator (`--schedule-install`, `--schedule-status`, `--schedule-remove`)**: Unattended morning priming background tasks for Windows Task Scheduler, Linux crontab, and macOS launchd. Full Tri-Engine Parity.
- [**#25**](https://github.com/joseamair/agent-quota-tracker/issues/25) - **Shell Prompt & Status Bar Integration (`--prompt`, `--prompt-format`)**: Ultra-fast (<15ms) cached status segments for Starship, Oh-My-Posh, tmux, and PowerShell `$PROFILE` with dynamic mathematical countdown engine and full Tri-Engine Parity.
- [**#20**](https://github.com/joseamair/agent-quota-tracker/issues/20) - **Native Desktop Toast Notifications (`--notify`, `--test-notify`)**: Merged in PR #26. Zero third-party dependencies, cross-platform (Windows, macOS, Linux), full Tri-Engine Parity.

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
