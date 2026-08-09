import sys
import subprocess
import logging
from server.tools.tool_executor import register_tool
from server.tools.tool_result import ToolResult

logger = logging.getLogger(__name__)

def show_notification(title: str, message: str) -> ToolResult:
    """Dispatches a native Windows system tray balloon notification using PowerShell.
    Does not require any third-party Python dependencies.
    """
    if sys.platform != "win32":
        return ToolResult(
            status="error",
            data={"title": title, "message": message},
            summary="Notifications are only supported on Windows.",
            error="Non-Windows OS detected."
        )

    # Clean strings to prevent PowerShell command injections
    safe_title = title.replace("'", "''").strip()
    safe_message = message.replace("'", "''").strip()

    # Powershell command to show balloon tip (loading forms and drawing libraries)
    ps_command = (
        "[void] [System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms'); "
        "[void] [System.Reflection.Assembly]::LoadWithPartialName('System.Drawing'); "
        "$notification = New-Object System.Windows.Forms.NotifyIcon; "
        "$notification.Icon = [System.Drawing.SystemIcons]::Information; "
        f"$notification.BalloonTipTitle = '{safe_title}'; "
        f"$notification.BalloonTipText = '{safe_message}'; "
        "$notification.Visible = $true; "
        "$notification.ShowBalloonTip(5000); "
        "Start-Sleep -Seconds 2; "
        "$notification.Dispose();"
    )

    try:
        # Launch powershell in background (non-blocking process spawn)
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps_command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        )
        return ToolResult(
            status="success",
            data={"title": title, "message": message},
            summary="Dispatched system notification."
        )
    except Exception as e:
        err_msg = f"Failed to spawn notification process: {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(
            status="error",
            data={"title": title, "message": message},
            summary="Could not trigger notification.",
            error=err_msg
        )

# Register with central executor
register_tool("show_notification", show_notification)
