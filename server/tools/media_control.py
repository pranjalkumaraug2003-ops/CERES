import sys
import logging
from server.tools.tool_executor import register_tool
from server.tools.tool_result import ToolResult

logger = logging.getLogger(__name__)

# Virtual key codes on Windows
VK_MAP = {
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
    "play_pause": 0xCD,
    "next": 0xB0,
    "prev": 0xB1
}

def media_control(action: str) -> ToolResult:
    """Controls the local Windows media stack by simulating multimedia keyboard events."""
    action_key = action.lower().strip()
    
    if action_key not in VK_MAP:
        return ToolResult(
            status="error",
            data={"action": action},
            summary="Invalid media control action requested.",
            error=f"Action '{action}' is not supported. Must be one of: {list(VK_MAP.keys())}"
        )

    if sys.platform != "win32":
        return ToolResult(
            status="error",
            data={"action": action},
            summary="Media control is only supported on Windows systems.",
            error="Non-Windows OS detected."
        )

    try:
        import ctypes
        vk_code = VK_MAP[action_key]
        
        # Simulate key press
        ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
        # Simulate key release
        ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)
        
        # Double trigger volume change slightly to make it noticeable (e.g. increase by 4%)
        if action_key in ("volume_up", "volume_down"):
            ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0)

        return ToolResult(
            status="success",
            data={"action": action_key, "vk_code": vk_code},
            summary=f"Triggered media action: {action_key}."
        )
    except Exception as e:
        err_msg = f"Failed to execute keyboard simulation for '{action_key}': {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(
            status="error",
            data={"action": action_key},
            summary=f"Failed to perform media control: {action_key}.",
            error=err_msg
        )

# Register with central executor
register_tool("media_control", media_control)
