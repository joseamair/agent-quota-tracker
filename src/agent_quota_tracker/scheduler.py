"""OS-Level Automated Morning Priming Task Generator.

Registers, inspects, and removes persistent background scheduled tasks:
- Windows: Windows Task Scheduler via ScheduledTasks PowerShell cmdlets
- Linux: User crontab (crontab -l)
- macOS: launchd LaunchAgent (~/Library/LaunchAgents/com.agentquotatracker.priming.plist)
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

TASK_NAME = "AgentQuotaTrackerMorningPriming"
MACOS_LABEL = "com.agentquotatracker.priming"


def get_schedule_log_file() -> Path:
    log_dir = Path(os.path.expanduser("~")) / ".agent_quota_tracker"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "schedule.log"


def append_schedule_log(message: str) -> None:
    try:
        log_file = get_schedule_log_file()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{now_str}] {message}\n")
    except Exception:
        pass


def validate_time_format(time_str: str) -> tuple[int, int]:
    """Validates and parses a 'HH:MM' 24-hour time string into (hour, minute)."""
    if not time_str or not time_str.strip():
        raise ValueError("Time string cannot be empty. Expected HH:MM (e.g. 07:30).")
    parts = time_str.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid time format '{time_str}'. Expected HH:MM in 24-hour format (e.g. 07:30).")
    try:
        h = int(parts[0])
        m = int(parts[1])
    except ValueError:
        raise ValueError(f"Non-numeric values in time '{time_str}'. Expected HH:MM.")

    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Time out of range '{time_str}'. Hour must be 0-23, minute 0-59.")

    return h, m


def get_repo_dir() -> Optional[Path]:
    """Attempts to find the agent-quota-tracker repository root directory."""
    candidates = [
        Path.cwd(),
        Path(__file__).resolve().parent.parent.parent,
        Path.home() / "wsl_files" / "personal_projects" / "agents_dashboard",
    ]
    for c in candidates:
        if (c / "agents.ps1").exists() or (c / "agents_native.ps1").exists() or (c / "pyproject.toml").exists():
            return c
    return None


def get_runner_details(notify: bool = True) -> tuple[str, list[str], str]:
    """Returns (executable, arguments, working_directory) to run poke non-interactively."""
    repo = get_repo_dir()
    repo_str = str(repo) if repo else str(Path.cwd())
    system = platform.system().lower()

    if system == "windows":
        native_ps = repo / "agents_native.ps1" if repo else None
        if native_ps and native_ps.exists():
            args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(native_ps), "-Poke"]
            if notify:
                args.append("-Notify")
            return "powershell.exe", args, repo_str

        # Fallback to agents.ps1
        ps_wrapper = repo / "agents.ps1" if repo else None
        if ps_wrapper and ps_wrapper.exists():
            args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps_wrapper), "--poke"]
            if notify:
                args.append("--notify")
            return "powershell.exe", args, repo_str

        # Fallback to python / agents CLI
        agents_bin = shutil.which("agents")
        if agents_bin:
            args = ["--poke"]
            if notify:
                args.append("--notify")
            return agents_bin, args, repo_str

        args = [str(repo / "agents.py") if repo else "agents.py", "--poke"]
        if notify:
            args.append("--notify")
        return sys.executable, args, repo_str

    else:
        # Linux / macOS
        agents_bin = shutil.which("agents")
        if agents_bin:
            args = ["--poke"]
            if notify:
                args.append("--notify")
            return agents_bin, args, repo_str

        sh_script = repo / "agents.sh" if repo else None
        if sh_script and sh_script.exists():
            args = ["--poke"]
            if notify:
                args.append("--notify")
            return str(sh_script), args, repo_str

        args = [str(repo / "agents.py") if repo else "agents.py", "--poke"]
        if notify:
            args.append("--notify")
        return sys.executable, args, repo_str


# ---------------------------------------------------------------------------
# Windows Task Scheduler Implementation
# ---------------------------------------------------------------------------

def _install_windows(time_str: str, notify: bool = True, frequency: str = "daily") -> dict[str, Any]:
    h, m = validate_time_format(time_str)
    formatted_time = f"{h:02d}:{m:02d}"
    exe, args, cwd = get_runner_details(notify=notify)
    arg_str = " ".join(f'"{a}"' if " " in a else a for a in args)

    freq = frequency.lower()
    if freq == "once":
        sched_desc = f"Once at {formatted_time}"
        trigger_code = f"""
$targetDt = (Get-Date).Date.AddHours({h}).AddMinutes({m})
if ($targetDt -le (Get-Date)) {{ $targetDt = $targetDt.AddDays(1) }}
$trigger = New-ScheduledTaskTrigger -Once -At $targetDt
"""
    elif freq in ("weekdays", "weekday", "workdays"):
        sched_desc = f"Weekdays at {formatted_time}"
        trigger_code = f"$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At '{formatted_time}'"
    else:
        sched_desc = f"Daily at {formatted_time}"
        trigger_code = f"$trigger = New-ScheduledTaskTrigger -Daily -At '{formatted_time}'"

    ps_script = f"""
$action = New-ScheduledTaskAction -Execute '{exe}' -Argument '{arg_str}' -WorkingDirectory '{cwd}'
{trigger_code}
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action -Trigger $trigger -Settings $settings -Force
"""
    res = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        return {"success": False, "message": f"Failed to register Windows scheduled task: {res.stderr.strip() or res.stdout.strip()}"}

    append_schedule_log(f"Scheduled task installed: {sched_desc} (Windows Task Scheduler)")
    return {
        "success": True,
        "task_name": TASK_NAME,
        "platform": "Windows Task Scheduler",
        "time": formatted_time,
        "frequency": freq,
        "schedule": sched_desc,
        "notify": notify,
        "command": f"{exe} {arg_str}",
        "working_dir": cwd,
        "log_file": str(get_schedule_log_file()),
    }


def _status_windows() -> dict[str, Any]:
    ps_script = f"""
$t = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue
if ($t) {{
    $info = Get-ScheduledTaskInfo -TaskName '{TASK_NAME}'
    $nextRun = if ($info.NextRunTime -and $info.NextRunTime.Year -gt 2000) {{ $info.NextRunTime.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ 'Pending' }}
    $lastRun = if ($info.LastRunTime -and $info.LastRunTime.Year -gt 2000) {{ $info.LastRunTime.ToString('yyyy-MM-dd HH:mm:ss') }} else {{ 'Never' }}
    [PSCustomObject]@{{
        Installed = $true
        TaskName = '{TASK_NAME}'
        Platform = 'Windows Task Scheduler'
        State = $t.State.ToString()
        NextRunTime = $nextRun
        LastRunTime = $lastRun
        LastResult = $info.LastTaskResult
    }} | ConvertTo-Json
}} else {{
    [PSCustomObject]@{{
        Installed = $false
        TaskName = '{TASK_NAME}'
        Platform = 'Windows Task Scheduler'
    }} | ConvertTo-Json
}}
"""
    res = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        text=True,
    )
    if res.returncode == 0 and res.stdout.strip():
        try:
            data = json.loads(res.stdout.strip())
            data["log_file"] = str(get_schedule_log_file())
            return data
        except Exception:
            pass
    return {"Installed": False, "TaskName": TASK_NAME, "Platform": "Windows Task Scheduler", "log_file": str(get_schedule_log_file())}


def _remove_windows() -> dict[str, Any]:
    ps_script = f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue"
    res = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        text=True,
    )
    append_schedule_log(f"Scheduled task removed (Windows Task Scheduler)")
    return {"success": res.returncode == 0, "message": f"Task '{TASK_NAME}' removed from Windows Task Scheduler."}


# ---------------------------------------------------------------------------
# Linux Crontab Implementation
# ---------------------------------------------------------------------------

def _install_linux(time_str: str, notify: bool = True) -> dict[str, Any]:
    h, m = validate_time_format(time_str)
    formatted_time = f"{h:02d}:{m:02d}"
    exe, args, cwd = get_runner_details(notify=notify)
    arg_str = " ".join(args)
    log_file = get_schedule_log_file()
    cron_cmd = f"cd '{cwd}' && {exe} {arg_str} >> '{log_file}' 2>&1"
    cron_entry = f"{m} {h} * * * {cron_cmd} # {TASK_NAME}"

    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    current = res.stdout if res.returncode == 0 else ""
    lines = [line for line in current.splitlines() if TASK_NAME not in line and line.strip()]
    lines.append(cron_entry)
    new_crontab = "\n".join(lines) + "\n"

    p = subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
    if p.returncode != 0:
        return {"success": False, "message": f"Failed to install crontab: {p.stderr.strip()}"}

    append_schedule_log(f"Scheduled task installed: Daily at {formatted_time} (Linux Crontab)")
    return {
        "success": True,
        "task_name": TASK_NAME,
        "platform": "Linux Crontab",
        "time": formatted_time,
        "notify": notify,
        "command": cron_cmd,
        "log_file": str(log_file),
    }


def _status_linux() -> dict[str, Any]:
    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if res.returncode == 0:
        for line in res.stdout.splitlines():
            if TASK_NAME in line and not line.strip().startswith("#"):
                parts = line.split()
                time_str = f"{int(parts[1]):02d}:{int(parts[0]):02d}" if len(parts) >= 2 else "Unknown"
                return {
                    "Installed": True,
                    "TaskName": TASK_NAME,
                    "Platform": "Linux Crontab",
                    "State": "Active",
                    "ScheduleTime": time_str,
                    "NextRunTime": f"Daily at {time_str}",
                    "LastRunTime": "Check schedule.log",
                    "log_file": str(get_schedule_log_file()),
                }
    return {"Installed": False, "TaskName": TASK_NAME, "Platform": "Linux Crontab", "log_file": str(get_schedule_log_file())}


def _remove_linux() -> dict[str, Any]:
    res = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if res.returncode == 0:
        lines = [line for line in res.stdout.splitlines() if TASK_NAME not in line]
        new_crontab = "\n".join(lines) + "\n" if lines else ""
        if new_crontab:
            subprocess.run(["crontab", "-"], input=new_crontab, text=True, capture_output=True)
        else:
            subprocess.run(["crontab", "-r"], capture_output=True)
    append_schedule_log("Scheduled task removed (Linux Crontab)")
    return {"success": True, "message": f"Task '{TASK_NAME}' removed from crontab."}


# ---------------------------------------------------------------------------
# macOS Launchd Implementation
# ---------------------------------------------------------------------------

def _get_macos_plist_path() -> Path:
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    return agents_dir / f"{MACOS_LABEL}.plist"


def _install_macos(time_str: str, notify: bool = True) -> dict[str, Any]:
    h, m = validate_time_format(time_str)
    formatted_time = f"{h:02d}:{m:02d}"
    exe, args, cwd = get_runner_details(notify=notify)
    log_file = str(get_schedule_log_file())
    plist_path = _get_macos_plist_path()

    program_args = [exe] + args
    program_args_xml = "\n".join(f"        <string>{a}</string>" for a in program_args)

    plist_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{MACOS_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{program_args_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{cwd}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{h}</integer>
        <key>Minute</key>
        <integer>{m}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_file}</string>
    <key>StandardErrorPath</key>
    <string>{log_file}</string>
</dict>
</plist>
"""
    plist_path.write_text(plist_xml, encoding="utf-8")
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    p = subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True, text=True)
    if p.returncode != 0:
        return {"success": False, "message": f"Failed to load launchd agent: {p.stderr.strip()}"}

    append_schedule_log(f"Scheduled task installed: Daily at {formatted_time} (macOS LaunchAgent)")
    return {
        "success": True,
        "task_name": TASK_NAME,
        "platform": "macOS LaunchAgent",
        "time": formatted_time,
        "notify": notify,
        "plist": str(plist_path),
        "log_file": log_file,
    }


def _status_macos() -> dict[str, Any]:
    plist_path = _get_macos_plist_path()
    if plist_path.exists():
        res = subprocess.run(["launchctl", "list", MACOS_LABEL], capture_output=True, text=True)
        return {
            "Installed": True,
            "TaskName": TASK_NAME,
            "Platform": "macOS LaunchAgent",
            "State": "Loaded" if res.returncode == 0 else "Installed (Unloaded)",
            "Plist": str(plist_path),
            "log_file": str(get_schedule_log_file()),
        }
    return {"Installed": False, "TaskName": TASK_NAME, "Platform": "macOS LaunchAgent", "log_file": str(get_schedule_log_file())}


def _remove_macos() -> dict[str, Any]:
    plist_path = _get_macos_plist_path()
    if plist_path.exists():
        subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        try:
            plist_path.unlink()
        except Exception:
            pass
    append_schedule_log("Scheduled task removed (macOS LaunchAgent)")
    return {"success": True, "message": f"Task '{TASK_NAME}' removed from launchd."}


# ---------------------------------------------------------------------------
# Cross-Platform Unified API
# ---------------------------------------------------------------------------

def install_schedule(time_str: str = "07:30", notify: bool = True, frequency: str = "daily") -> dict[str, Any]:
    system = platform.system().lower()
    if system == "windows":
        return _install_windows(time_str, notify=notify, frequency=frequency)
    elif system == "darwin":
        return _install_macos(time_str, notify=notify)
    else:
        return _install_linux(time_str, notify=notify)


def get_schedule_status() -> dict[str, Any]:
    system = platform.system().lower()
    if system == "windows":
        return _status_windows()
    elif system == "darwin":
        return _status_macos()
    else:
        return _status_linux()


def remove_schedule() -> dict[str, Any]:
    system = platform.system().lower()
    if system == "windows":
        return _remove_windows()
    elif system == "darwin":
        return _remove_macos()
    else:
        return _remove_linux()
