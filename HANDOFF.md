# 🤝 Agent Handoff Document & Engineering Context

Welcome, incoming AI Coding Agent! This document gives you immediate, end-to-end technical context to pick up work smoothly on `agent-quota-tracker` with zero friction.

---

## 📌 Executive Summary

- **Repository**: [`agent-quota-tracker`](https://github.com/joseamair/agent-quota-tracker)
- **Current Version**: `v1.4.0` (Released 2026-10-05)
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
> 4. **Verified Commits & Releases Rule (No Direct Pushes to `main`)**:
>    - **NEVER** push commits directly to `main` (`git push origin main`). Direct pushes create unsigned local commits and will NOT receive GitHub's verified signature.
>    - **ALL** changes—including bugfixes, features, documentation updates, and release version bumps—MUST be branched (`feat/...`, `chore/...`, `release/...`), submitted as a Pull Request (`gh pr create`), and squash-merged via GitHub (`gh pr merge --squash --admin`).
>    - This guarantees that GitHub's servers generate the squashed commit and sign it with GitHub's verified GPG key (`web-flow`), ensuring that all commits and release tags display the verified seal:
>      `"This commit was created on GitHub.com and signed with GitHub’s verified signature."`

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
# 1. Run Python unit tests (must pass 155/155)
uv run --no-sync pytest -v

# 2. Syntax check standalone script
uv run --no-sync python -m py_compile agents.py

# 3. CLI help check
uv run --no-sync agents --help

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

1. [**#36**](https://github.com/joseamair/agent-quota-tracker/issues/36) - **Track Repository Visitor Traffic and Views using Free GitHub Native APIs & Actions**:
   - *Status*: Architectural specification and API blueprint posted. Ready for implementation.
   - *Mechanism*: Scheduled native GitHub Actions workflow (`cron: '0 0 * * *'`) querying 4 free endpoints (`/traffic/views`, `/traffic/clones`, `/traffic/popular/referrers`, `/traffic/popular/paths`) with `${{ secrets.GITHUB_TOKEN }}`. Solves GitHub's 14-day data retention limit by committing permanent historical timeseries into an isolated branch or directory without 3rd-party services.
   - *Integration*: Future `agents traffic` CLI view and Web Dashboard visitor traffic widget.

2. [**#58**](https://github.com/joseamair/agent-quota-tracker/issues/58) - **Smart Agent Router and Optimal Account Recommender (`agents route` / `agents ask`)**:
   - *Status*: Ready for implementation.
   - *Mechanism*: Analyzes real-time fleet state from local cache (`cache.json`) to recommend the optimal account right now based on rolling window status, remaining percentage, and time until reset. Provides `agents ask "<prompt>"` proxy auto-routing lightweight queries to the least-utilized eligible agent to preserve deep focus quota.
   - *Integration*: New `router.py` module, CLI commands `agents route` and `agents ask`.

3. [**#59**](https://github.com/joseamair/agent-quota-tracker/issues/59) - **Context Packager and Instant Agent Handoff (`agents handoff <target>`)**:
   - *Status*: Ready for implementation.
   - *Mechanism*: Inspects local git workspace (branch, status, recent commits, diff summary) and generates a compact, high-density markdown transition prompt when an agent hits its 5h limit. Supports `--clip` to copy directly to clipboard via native OS commands.
   - *Integration*: New `handoff.py` module, CLI command `agents handoff [agent]`, and Web Dashboard 1-click handoff button on cards $\ge 90\%$.

4. [**#60**](https://github.com/joseamair/agent-quota-tracker/issues/60) - **Predictive Depletion Velocity and Pacing Forecaster (`agents forecast`)**:
   - *Status*: Ready for implementation.
   - *Mechanism*: Analyzes consumption velocity ($\Delta \% / \Delta t$) from SQLite `history.db` to project the exact minute of quota depletion. Emits pacing advice to avoid midday lockouts.
   - *Integration*: New `forecast.py` module, CLI command `agents forecast`, and projected trendlines on Web Dashboard SVG burndown chart.

5. [**#61**](https://github.com/joseamair/agent-quota-tracker/issues/61) - **Subscription Value Arbitrage and ROI Scorecard (`agents roi` / `agents report`)**:
   - *Status*: Ready for implementation.
   - *Mechanism*: Maps cumulative token utilization in `history.db` against commercial direct API pricing benchmarks (Claude Sonnet ~$9/M blended, Codex/GPT-4o ~$6.25/M blended) to calculate extracted value vs flat $20/mo subscription costs.
   - *Integration*: New `roi.py` module, CLI commands `agents roi` and `agents report --today`, and Web Dashboard ROI card.

6. [**#62**](https://github.com/joseamair/agent-quota-tracker/issues/62) - **Quota-Aware Git Pre-Commit & Pre-Push Guard (`agents hook`)**:
   - *Status*: Ready for implementation.
   - *Mechanism*: Installs native zero-dependency git hooks (`.git/hooks/pre-commit`, `pre-push`) reading local cache (`cache.json`) in <10ms to verify agent health before running AI linters/commit-generators, gracefully skipping or falling back if quota is exhausted.
   - *Integration*: New `hooks.py` module, CLI commands `agents hook install/remove/status`.

### Recently Delivered
- [**#55**](https://github.com/joseamair/agent-quota-tracker/issues/55) / [**#56**](https://github.com/joseamair/agent-quota-tracker/pull/56) - **Interactive Quick Filter & Search in Terminal TUI (`agents tui`)**: Added real-time interactive search prompt (`/` key) with live visual query indicator (`🔍 Filter: query█`), multi-field substring matching, semantic keyword shortcuts (`idle`, `active`, `expired`, `auth`), `Backspace` and `Esc` navigation, and filtered poke-all (`a`). Full Tri-Engine Parity across `src/agent_quota_tracker/tui.py`, `agents.py`, and test suite (`test_tui.py`).
- [**#53**](https://github.com/joseamair/agent-quota-tracker/issues/53) / [**#54**](https://github.com/joseamair/agent-quota-tracker/pull/54) - **Community Agent Trackers General Availability (GA)**: Graduated Cursor, Windsurf, GitHub Copilot CLI, and Aider/OpenRouter from Beta to GA. Added universal environment variable fallbacks, token expiration inspection, and Proactive Auth Health Guard remediation hints. Full Tri-Engine Parity across `src/agent_quota_tracker/trackers/`, `agents.py`, and `agents_native.ps1`.
- [**#50**](https://github.com/joseamair/agent-quota-tracker/issues/50) - **Interactive Full-Screen Terminal TUI (`agents tui`)**: Implemented full-screen keyboard-driven terminal dashboard operating in alternate screen buffer (`\033[?1049h`). Features row navigation (`↑`/`k`, `↓`/`j`), single poke (`p`), force poke (`f`), poke all (`a`), refresh (`r`), help modal (`?`), selected account inspector, colored progress bars, and clean exit. Full Tri-Engine Parity across `src/agent_quota_tracker/tui.py`, `agents.py`, and `agents_native.ps1 -Tui`.
- [**#49**](https://github.com/joseamair/agent-quota-tracker/pull/49) / [**#48**](https://github.com/joseamair/agent-quota-tracker/issues/48) - **Prometheus Metrics Endpoint & Timeseries CSV Export**: Added standard Prometheus version 0.0.4 text format metrics exporter (`GET /metrics` and `agents --metrics`) exposing 7 key gauges with rich labels. Added RFC 4180 CSV export for historical snapshots and priming logs (`agents export --csv` and `GET /api/export`) with days/agent filtering and file destination options. Full Tri-Engine Parity across `src/agent_quota_tracker/metrics.py`, `history.py`, `agents.py`, and `agents_native.ps1`.
- [**#47**](https://github.com/joseamair/agent-quota-tracker/pull/47) / [**#46**](https://github.com/joseamair/agent-quota-tracker/issues/46) - **Proactive Token Expiration & Auth Health Guard**: Local OAuth token inspection (`expiresAt` epoch ms), HTTP 401/403 detection, `⚠️ EXPIRED` / `⚠️ NO AUTH` visual badges, dedicated CLI & Dashboard `🔐 Authentication Health Alerts` remediation panel, and poke skip guards. Full Tri-Engine Parity.
- [**#43**](https://github.com/joseamair/agent-quota-tracker/pull/43) - **Official v1.2.1 Release & Verified Commits Rule**: Bumped version to `v1.2.1` across project files and formalized the Verified Commits & Releases Rule (all commits must be PR-squashed via GitHub's `web-flow` signer).
- [**#42**](https://github.com/joseamair/agent-quota-tracker/pull/42) - **Live In-Place Status Table Stream for Auto-Checker (`agents auto`, `--auto-poke`)**: Added real-time in-place status table stream with second-by-second countdown for active accounts, zero-prompt-token periodic quota utilization refetching (default every 15s via `--refresh-interval`), and early idle detection. Full Tri-Engine Parity across `src/agent_quota_tracker/cli.py`, `agents.py`, and `agents_native.ps1`.
- [**#41**](https://github.com/joseamair/agent-quota-tracker/issues/41) / [**#40**](https://github.com/joseamair/agent-quota-tracker/pull/40) - **Interactive Web Dashboard Charts (Hover Tooltips, Multi-Metric Selector, Account Checkboxes, Drag Zoom)**: Enhanced historical burn-down chart with vertical crosshair scrubbing, point halos, glassmorphic floating tooltips, 4-way metric selection (5h %, weekly %, time remaining, estimated tokens computed from tier capacity), dynamic per-account legend checkboxes with `localStorage` persistence, and horizontal timeline box drag-to-zoom with reset button. Full Tri-Engine Parity.
- [**#37**](https://github.com/joseamair/agent-quota-tracker/pull/37) - **Historical Poke & Activity Backfill Importer**: Multi-source scanner parsing legacy `~/.agent_quota_tracker/schedule.log` and `~/.agents_dashboard/state.json`. Safe, zero-duplicate ingestion into SQLite `history.db` (`pokes` and `snapshots`), immediately backfilling past weeks of usage trends and diurnal peak hours. Added `agents --backfill`, `python agents.py --backfill`, `agents_native.ps1 -Backfill`, and interactive `📥 Backfill` button on Web Dashboard.
- [**#23**](https://github.com/joseamair/agent-quota-tracker/issues/23) - **Local SQLite Historical Analytics & Burndown Charts**: Embedded SQLite timeseries database under `~/.agent_quota_tracker/history.db` storing quota snapshots and poke records with 60s deduplication. Added `agents --analytics`, `--insights`, and `agents analytics [--days N]` displaying active time ratio, top 3 peak hours, optimal morning priming recommendation, and 24-hour diurnal distribution. Embedded interactive SVG 7-day velocity burn-down chart, 24-hour activity bars, and period selector (24h, 3d, 7d, 14d) in Web Dashboard with `/api/history` and `/api/analytics` endpoints. Full Tri-Engine Parity.
- [**#46**](https://github.com/joseamair/agent-quota-tracker/issues/46) - **Proactive Token Expiration & Auth Health Guard**: Local OAuth token inspection (`expiresAt` epoch ms), HTTP 401/403 detection, `⚠️ EXPIRED` / `⚠️ NO AUTH` visual badges, dedicated CLI & Dashboard `🔐 Authentication Health Alerts` remediation panel, and poke skip guards. Full Tri-Engine Parity.
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
