# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

---

## 🔒 Credential Safety & Architecture

`agents-dashboard` is designed with strict local privacy principles:

1. **Zero External Data Exfiltration**:
   - Authentication tokens and credentials stored in local directories (such as `~/.ccs/instances/` and `~/.claude.json`) are read exclusively in memory.
   - Credentials are never logged, telemetry-tracked, uploaded, or transmitted to any third-party analytics or external telemetry servers.
   - When fetching live quota stats, requests are directed strictly to the official provider endpoint (e.g., `https://api.anthropic.com/api/oauth/usage`).

2. **Non-Interactive Execution**:
   - CLI pokes (`ccs`, `codex`, `agy`) execute non-interactively using ephemeral sessions with `stdin` redirected to `DEVNULL`.
   - Temporary poke sessions do not modify existing chat threads or project files.

3. **Never Commit Credentials**:
   - Always ensure that `.credentials.json`, `.claude.json`, `.env`, and session history files remain outside version control.
   - The `.gitignore` in this repository enforces exclusion of local state files and logs.

---

## Reporting a Vulnerability

If you discover a security vulnerability within `agents-dashboard`:

1. **Do not create a public GitHub issue.**
2. Send an email to the repository maintainer or open a private GitHub Security Advisory.
3. Include detailed steps to reproduce the vulnerability, along with your environment details (OS, Python version, PowerShell version).
4. You will receive an acknowledgment within 48 hours, followed by updates on the patch and release timeline.
