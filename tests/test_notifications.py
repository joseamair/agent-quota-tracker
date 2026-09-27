"""Unit tests for desktop notifications module."""

from unittest.mock import patch, MagicMock
from agent_quota_tracker.notifications import send_notification


def test_send_notification_windows():
    with patch("platform.system", return_value="Windows"), \
         patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        result = send_notification("⚡ Antigravity", "Window primed successfully!")

        assert result is True
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        assert cmd_args[0] == "powershell.exe"
        assert "⚡ Antigravity" in cmd_args[-1]
        assert "Window primed successfully!" in cmd_args[-1]


def test_send_notification_macos():
    with patch("platform.system", return_value="Darwin"), \
         patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        result = send_notification("⚡ Claude", "5h window is active")

        assert result is True
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        assert cmd_args[0] == "osascript"
        assert 'display notification "5h window is active" with title "⚡ Claude"' in cmd_args[-1]


def test_send_notification_linux():
    with patch("platform.system", return_value="Linux"), \
         patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        result = send_notification("⚡ Codex", "Quota reset in 30m")

        assert result is True
        mock_popen.assert_called_once()
        cmd_args = mock_popen.call_args[0][0]
        assert cmd_args == ["notify-send", "⚡ Codex", "Quota reset in 30m"]


def test_send_notification_sanitizes_input():
    with patch("platform.system", return_value="Windows"), \
         patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        result = send_notification('Title with "quotes" and \'apostrophe\'', 'Line 1\nLine 2')

        assert result is True
        cmd_args = mock_popen.call_args[0][0]
        ps_script = cmd_args[-1]
        assert '\nLine 2' not in ps_script  # Newline converted to space
        assert 'Title with \\"quotes\\"' in ps_script


def test_send_notification_graceful_on_exception():
    with patch("platform.system", return_value="Windows"), \
         patch("subprocess.Popen", side_effect=OSError("Process creation failed")):
        result = send_notification("Title", "Message")
        assert result is False  # Never raises
