"""Cross-platform desktop toast notification service.

Supports native OS notifications without third-party dependencies:
- Windows: WinRT Toast via background PowerShell
- macOS: osascript notification
- Linux: notify-send (libnotify)
"""

import os
import platform
import subprocess
import sys


def send_notification(title: str, message: str) -> bool:
    """Send a native OS desktop notification.

    Args:
        title: Notification header / title.
        message: Notification body text.

    Returns:
        True if the notification command dispatched without errors, False otherwise.
    """
    system = platform.system().lower()

    # Clean strings to prevent injection or script breakages
    safe_title = title.replace('"', '\\"').replace("'", "’")
    safe_message = message.replace('"', '\\"').replace("'", "’").replace("\n", " ")

    try:
        if system == "windows":
            # Native Windows 10/11 WinRT Toast via powershell.exe
            ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName('text')
$null = $textNodes.Item(0).AppendChild($template.CreateTextNode('{safe_title}'))
$null = $textNodes.Item(1).AppendChild($template.CreateTextNode('{safe_message}'))
$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}}\\WindowsPowerShell\\v1.0\\powershell.exe')
$notifier.Show($toast)
"""
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True

        elif system == "darwin":
            # macOS native notification via AppleScript
            apple_script = f'display notification "{safe_message}" with title "{safe_title}"'
            subprocess.Popen(
                ["osascript", "-e", apple_script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            return True

        elif system == "linux":
            # Linux desktop notification via notify-send (libnotify)
            subprocess.Popen(
                ["notify-send", safe_title, safe_message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            return True

    except Exception:
        # Notifications should never crash the main application
        return False

    return False
