import os
import sys
import subprocess
import logging
from datetime import datetime
from server.tools.tool_executor import register_tool
from server.tools.tool_result import ToolResult
from server.services.system_service import get_system_stats

logger = logging.getLogger(__name__)

async def get_system_stats_tool() -> ToolResult:
    """Retrieves current CPU, RAM, and Disk metrics of the host machine."""
    try:
        stats = await get_system_stats()
        # Formulate a clean summary for voice synthesis
        summary = (
            f"CPU usage is at {stats.get('cpu_percent') or 0} percent. "
            f"You have {stats.get('ram_used_gb') or 0} gigabytes of RAM used out of {stats.get('ram_total_gb') or 0} gigabytes total. "
            f"Battery is at {stats.get('battery_percent') or 100} percent."
        )
        return ToolResult(
            status="success",
            data=stats,
            summary=summary
        )
    except Exception as e:
        err_msg = f"Failed to gather system stats: {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(status="error", data={}, summary="Could not retrieve system stats.", error=err_msg)

def lock_pc_tool() -> ToolResult:
    """Locks the Windows workstation instantly."""
    if sys.platform != "win32":
        return ToolResult(status="error", data={}, summary="PC Lock is only supported on Windows OS.")
        
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return ToolResult(
            status="success",
            data={},
            summary="Locking the computer now."
        )
    except Exception as e:
        err_msg = f"LockWorkStation dll call failed: {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(status="error", data={}, summary="Failed to lock computer.", error=err_msg)

def take_screenshot_tool() -> ToolResult:
    """Takes a screenshot of the main desktop and saves it to the Windows Desktop folder."""
    try:
        from PIL import ImageGrab
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        os.makedirs(desktop_dir, exist_ok=True)
        
        file_name = f"screenshot_{ts}.png"
        path = os.path.join(desktop_dir, file_name)
        
        # Grab primary screen pixels and save
        screenshot = ImageGrab.grab()
        screenshot.save(path)
        
        return ToolResult(
            status="success",
            data={"filepath": path, "filename": file_name},
            summary=f"Screenshot taken and saved to Desktop as {file_name}."
        )
    except Exception as e:
        err_msg = f"Screenshot capture failed: {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(status="error", data={}, summary="Could not take screenshot.", error=err_msg)

def run_shell_command_tool(command: str) -> ToolResult:
    """[DANGEROUS] Runs a shell command on the host computer. Requires user confirmation."""
    try:
        res = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30.0
        )
        
        data = {
            "command": command,
            "returncode": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr
        }
        
        if res.returncode == 0:
            summary = f"Shell command executed successfully (returned 0)."
            return ToolResult(status="success", data=data, summary=summary)
        else:
            summary = f"Shell command failed with return code {res.returncode}."
            return ToolResult(status="partial", data=data, summary=summary, error=res.stderr.strip())
            
    except subprocess.TimeoutExpired:
        err_msg = "Command execution timed out after 30 seconds."
        logger.warning(err_msg)
        return ToolResult(status="error", data={"command": command}, summary="Shell command timed out.", error=err_msg)
    except Exception as e:
        err_msg = f"Failed to execute command: {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(status="error", data={"command": command}, summary="Shell command failed.", error=err_msg)

def delete_file_tool(filepath: str) -> ToolResult:
    """[DANGEROUS] Deletes a local file. Requires user confirmation."""
    target_path = os.path.abspath(filepath)
    
    if not os.path.exists(target_path):
        return ToolResult(
            status="error",
            data={"filepath": target_path},
            summary="File does not exist.",
            error=f"Path not found: {target_path}"
        )
        
    if os.path.isdir(target_path):
        return ToolResult(
            status="error",
            data={"filepath": target_path},
            summary="Target path is a directory. Folder deletion is not allowed.",
            error="Directory deletion is blocked."
        )

    try:
        os.remove(target_path)
        return ToolResult(
            status="success",
            data={"filepath": target_path},
            summary=f"Permanently deleted file: {os.path.basename(target_path)}."
        )
    except Exception as e:
        err_msg = f"File removal call failed: {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(
            status="error",
            data={"filepath": target_path},
            summary="Failed to delete file.",
            error=err_msg
        )

# Register with central executor
register_tool("get_system_stats", get_system_stats_tool)
register_tool("lock_pc", lock_pc_tool)
register_tool("take_screenshot", take_screenshot_tool)
register_tool("run_shell_command", run_shell_command_tool)
register_tool("delete_file", delete_file_tool)
