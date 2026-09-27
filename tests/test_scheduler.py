"""Unit tests for OS-level automated morning priming task generator."""

import json
import platform
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_quota_tracker.scheduler import (
    TASK_NAME,
    MACOS_LABEL,
    append_schedule_log,
    get_runner_details,
    get_schedule_log_file,
    get_schedule_status,
    install_schedule,
    remove_schedule,
    validate_time_format,
)


def test_validate_time_format_valid():
    assert validate_time_format("07:30") == (7, 30)
    assert validate_time_format("00:00") == (0, 0)
    assert validate_time_format("23:59") == (23, 59)
    assert validate_time_format("8:15") == (8, 15)
    assert validate_time_format("07:30:00") == (7, 30)


def test_validate_time_format_invalid():
    with pytest.raises(ValueError, match="cannot be empty"):
        validate_time_format("")

    with pytest.raises(ValueError, match="Invalid time format"):
        validate_time_format("0730")

    with pytest.raises(ValueError, match="Non-numeric values"):
        validate_time_format("07:xx")

    with pytest.raises(ValueError, match="out of range"):
        validate_time_format("24:00")

    with pytest.raises(ValueError, match="out of range"):
        validate_time_format("12:60")


def test_get_runner_details_windows():
    with patch("platform.system", return_value="Windows"):
        exe, args, cwd = get_runner_details(notify=True)
        assert exe == "powershell.exe"
        assert "-Poke" in args or "--poke" in args
        assert "-Notify" in args or "--notify" in args
        assert isinstance(cwd, str)


def test_get_runner_details_linux():
    with patch("platform.system", return_value="Linux"):
        exe, args, cwd = get_runner_details(notify=False)
        assert "--poke" in args
        assert "--notify" not in args


def test_append_schedule_log(tmp_path):
    log_file = tmp_path / "schedule.log"
    with patch("agent_quota_tracker.scheduler.get_schedule_log_file", return_value=log_file):
        append_schedule_log("Test schedule log entry")
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "Test schedule log entry" in content


def test_install_schedule_windows():
    with patch("platform.system", return_value="Windows"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        res = install_schedule(time_str="07:30", notify=True)

        assert res["success"] is True
        assert res["task_name"] == TASK_NAME
        assert res["platform"] == "Windows Task Scheduler"
        assert res["time"] == "07:30"
        mock_run.assert_called_once()
        cmd_called = mock_run.call_args[0][0]
        assert cmd_called[0] == "powershell.exe"
        ps_script = cmd_called[-1]
        assert "New-ScheduledTaskAction" in ps_script
        assert "New-ScheduledTaskTrigger" in ps_script
        assert "Register-ScheduledTask" in ps_script
        assert TASK_NAME in ps_script


def test_install_schedule_linux():
    with patch("platform.system", return_value="Linux"), \
         patch("subprocess.run") as mock_run:
        # First call: crontab -l (existing crontab)
        # Second call: crontab - (write new crontab)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="# existing crontab\n", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]

        res = install_schedule(time_str="08:15", notify=False)

        assert res["success"] is True
        assert res["platform"] == "Linux Crontab"
        assert res["time"] == "08:15"
        assert mock_run.call_count == 2
        # Check that second call piped the cron entry
        second_call_input = mock_run.call_args_list[1][1].get("input", "")
        assert "15 8 * * *" in second_call_input
        assert TASK_NAME in second_call_input


def test_install_schedule_macos(tmp_path):
    plist_file = tmp_path / f"{MACOS_LABEL}.plist"
    with patch("platform.system", return_value="Darwin"), \
         patch("agent_quota_tracker.scheduler._get_macos_plist_path", return_value=plist_file), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        res = install_schedule(time_str="07:45", notify=True)

        assert res["success"] is True
        assert res["platform"] == "macOS LaunchAgent"
        assert res["time"] == "07:45"
        assert plist_file.exists()
        plist_content = plist_file.read_text(encoding="utf-8")
        assert MACOS_LABEL in plist_content
        assert "<integer>7</integer>" in plist_content
        assert "<integer>45</integer>" in plist_content


def test_get_schedule_status_windows_installed():
    with patch("platform.system", return_value="Windows"), \
         patch("subprocess.run") as mock_run:
        payload = json.dumps({
            "Installed": True,
            "TaskName": TASK_NAME,
            "Platform": "Windows Task Scheduler",
            "State": "Ready",
            "NextRunTime": "2026-09-28 07:30:00",
            "LastRunTime": "Never",
            "LastResult": 0,
        })
        mock_run.return_value = MagicMock(returncode=0, stdout=payload, stderr="")

        status = get_schedule_status()

        assert status["Installed"] is True
        assert status["TaskName"] == TASK_NAME
        assert status["State"] == "Ready"


def test_get_schedule_status_windows_not_installed():
    with patch("platform.system", return_value="Windows"), \
         patch("subprocess.run") as mock_run:
        payload = json.dumps({
            "Installed": False,
            "TaskName": TASK_NAME,
            "Platform": "Windows Task Scheduler",
        })
        mock_run.return_value = MagicMock(returncode=0, stdout=payload, stderr="")

        status = get_schedule_status()

        assert status["Installed"] is False


def test_remove_schedule_windows():
    with patch("platform.system", return_value="Windows"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        res = remove_schedule()

        assert res["success"] is True
        mock_run.assert_called_once()
        ps_script = mock_run.call_args[0][0][-1]
        assert "Unregister-ScheduledTask" in ps_script
        assert TASK_NAME in ps_script


def test_remove_schedule_linux():
    with patch("platform.system", return_value="Linux"), \
         patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=f"30 7 * * * test # {TASK_NAME}\n", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]

        res = remove_schedule()

        assert res["success"] is True
