# Contributing to Agent Quota Tracker

Thank you for your interest in contributing to **Agent Quota Tracker**! This document provides guidelines and instructions for setting up your development environment, adding new AI agent trackers, and submitting pull requests.

---

## 🛠️ Development Setup

The project uses [uv](https://github.com/astral-sh/uv) as its package and virtual environment manager.

### Prerequisites
- Windows 10/11 (or Linux/macOS with compatible CLIs)
- Python 3.11+
- `uv` installed (`winget install astral-sh.uv` or `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`)
- PowerShell 7+ (`pwsh`) or Windows PowerShell 5.1

### Local Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/joseamair/agent-quota-tracker.git
   cd agent-quota-tracker
   ```

2. **Sync dependencies and initialize virtual environment**:
   ```bash
   uv sync
   ```

3. **Run local CLI commands during development**:
   ```powershell
   # Run directly via package entrypoint
   uv run agents --status

   # Or run the standalone script
   uv run python agents.py --status

   # Or test the PowerShell native implementation
   .\agents_native.ps1 -Status
   ```

---

## 🏗️ Architecture & Codebase Structure

```text
agent-quota-tracker/
├── src/
│   └── agents_dashboard/
│       ├── __init__.py
│       ├── cli.py             # CLI parser and Rich terminal table renderer
│       ├── core.py            # Orchestrator: queries trackers concurrently
│       ├── dashboard.py       # Embedded HTTP server and HTML dashboard generator
│       ├── models.py          # Data models: AgentStatus, PokeResult
│       ├── state.py           # Local persistence manager (~/.agents_dashboard/state.json)
│       └── trackers/
│           ├── base.py        # BaseTracker abstract base class & utility helpers
│           ├── claude.py      # Claude / Anthropic CCS instance tracker
│           ├── codex.py       # OpenAI Codex app-server tracker
│           └── agy.py         # Google Antigravity quota tracker
├── agents.py                  # Standalone all-in-one script (no local package install required)
├── agents_native.ps1          # Pure PowerShell implementation (zero Python dependency)
├── agents.ps1                 # PowerShell convenience runner
├── dashboard.html             # Standalone HTML dashboard with live JS countdown timers
└── pyproject.toml             # Project metadata, dependencies, and entrypoints
```

---

## ➕ How to Add a New AI Agent Tracker

We welcome trackers for other AI coding assistants (e.g., Cursor, GitHub Copilot, Roo Code, Aider, Windsurf).

### Step 1: Subclass `BaseTracker`
Create a new file in `src/agents_dashboard/trackers/<agent_name>.py`:

```python
from typing import Optional
from agents_dashboard.models import AgentStatus, PokeResult
from agents_dashboard.trackers.base import BaseTracker, extract_reply_snippet

class CustomAgentTracker(BaseTracker):
    @property
    def agent_id(self) -> str:
        return "custom-agent"

    @property
    def display_name(self) -> str:
        return "Custom Agent"

    @property
    def provider(self) -> str:
        return "CustomProvider"

    def get_status(self) -> AgentStatus:
        # 1. Query rate limit / local quota status
        is_active = ...
        used_pct = ...
        remaining_secs = ...
        return AgentStatus(
            id=self.agent_id,
            name=self.display_name,
            provider=self.provider,
            is_active=is_active,
            used_percent=used_pct,
            time_remaining_seconds=remaining_secs,
        )

    def poke(self, prompt: str = "Hello, how are you doing?", force: bool = False) -> PokeResult:
        # 2. Check if active (skip unless force=True)
        # 3. Trigger non-interactive turn with stdin=DEVNULL
        # 4. Extract reply snippet and re-query status to verify
        ...
```

### Step 2: Register Tracker in `core.py`
In `src/agents_dashboard/core.py`, import your tracker and add it to `get_default_trackers()`:

```python
from agents_dashboard.trackers.custom import CustomAgentTracker

def get_default_trackers() -> list[BaseTracker]:
    trackers: list[BaseTracker] = [
        # ... existing trackers
        CustomAgentTracker(),
    ]
    return trackers
```

### Step 3: Maintain Parity with `agents.py` and `agents_native.ps1`
Whenever feasible, add equivalent logic to `agents.py` and `agents_native.ps1` so that users running standalone Python or pure PowerShell have feature parity.

---

## 🎨 Code Style & Quality

- Keep functions modular, strongly typed, and documented with docstrings.
- Ensure cross-platform character encoding is handled cleanly (use `encoding="utf-8", errors="replace"` on subprocess calls).
- Normalize non-standard Unicode punctuation (smart quotes, dashes) to avoid console encoding crashes on Windows.

---

## 📬 Pull Request Process

1. Fork the repo and create your feature branch:
   ```bash
   git checkout -b feature/my-new-tracker
   ```
2. Commit your changes with clear, descriptive commit messages:
   ```bash
   git commit -m "feat(trackers): add support for CustomAgent"
   ```
3. Test all entrypoints:
   - `uv run agents --status`
   - `uv run agents --poke --force --agent custom-agent`
   - `.\agents_native.ps1 -Status`
4. Open a Pull Request referencing any related issues.
