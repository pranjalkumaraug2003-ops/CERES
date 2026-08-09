import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Directory path for permission audit logs
AUDITS_DIR = os.path.expanduser("~/.gemini/antigravity/logs/audits")

class ToolPermission:
    def __init__(
        self,
        requires_confirmation: bool = False,
        is_dangerous: bool = False,
        network_access: bool = False,
        filesystem_access: bool = False,
        system_access: bool = False,
        data_exfil_risk: bool = False,
    ):
        self.requires_confirmation = requires_confirmation
        self.is_dangerous = is_dangerous
        self.network_access = network_access
        self.filesystem_access = filesystem_access
        self.system_access = system_access
        self.data_exfil_risk = data_exfil_risk

    def to_dict(self) -> Dict[str, bool]:
        return {
            "requires_confirmation": self.requires_confirmation,
            "is_dangerous": self.is_dangerous,
            "network_access": self.network_access,
            "filesystem_access": self.filesystem_access,
            "system_access": self.system_access,
            "data_exfil_risk": self.data_exfil_risk,
        }

# Pre-defined permission definitions for local capability boundaries
TOOL_PERMISSIONS: Dict[str, ToolPermission] = {
    # Dangerous operations requiring user confirmation
    "delete_file": ToolPermission(requires_confirmation=True, is_dangerous=True, filesystem_access=True),
    "close_application": ToolPermission(requires_confirmation=True, is_dangerous=True, system_access=True),
    "send_email": ToolPermission(requires_confirmation=True, is_dangerous=True, network_access=True, data_exfil_risk=True),
    "run_shell_command": ToolPermission(requires_confirmation=True, is_dangerous=True, system_access=True, filesystem_access=True, network_access=True),
    "browser_automation": ToolPermission(requires_confirmation=True, is_dangerous=True, network_access=True, system_access=True),
    
    # Safe operations executed directly
    "open_app": ToolPermission(requires_confirmation=False, system_access=True),
    "get_system_stats": ToolPermission(requires_confirmation=False, system_access=True),
    "get_weather": ToolPermission(requires_confirmation=False, network_access=True),
    "search_web": ToolPermission(requires_confirmation=False, network_access=True),
    "get_unread_emails": ToolPermission(requires_confirmation=False, network_access=True),
    "get_calendar_events": ToolPermission(requires_confirmation=False, network_access=True),
    "take_screenshot": ToolPermission(requires_confirmation=False, system_access=True, filesystem_access=True),
    "lock_pc": ToolPermission(requires_confirmation=False, system_access=True),
    "media_control": ToolPermission(requires_confirmation=False, system_access=True),
    "create_reminder": ToolPermission(requires_confirmation=False),
    # Browser navigation: opens external windows — requires confirmation
    "open_url": ToolPermission(requires_confirmation=True, network_access=True, system_access=True),
    "play_youtube": ToolPermission(requires_confirmation=True, network_access=True, system_access=True),
    "open_maps": ToolPermission(requires_confirmation=True, network_access=True, system_access=True),
    # Finance tools: read-only network lookups, no confirmation needed
    "get_exchange_rate": ToolPermission(requires_confirmation=False, network_access=True),
    "get_gold_price": ToolPermission(requires_confirmation=False, network_access=True),
    "get_crypto_price": ToolPermission(requires_confirmation=False, network_access=True),
}

def get_tool_permission(tool_name: str) -> ToolPermission:
    """Retrieves the ToolPermission config for a tool.
    Defaults to a highly restrictive profiles for unregistered tools (fail secure).
    """
    return TOOL_PERMISSIONS.get(
        tool_name,
        # Default safety fallback: must confirm, dangerous, all access true
        ToolPermission(
            requires_confirmation=True,
            is_dangerous=True,
            network_access=True,
            filesystem_access=True,
            system_access=True,
            data_exfil_risk=True
        )
    )

def log_audit(
    tool_name: str,
    permission: ToolPermission,
    initiator: str,
    request_id: str,
    status: str,
    details: str = ""
) -> None:
    """Logs the execution attempt and authorization status of a tool execution.
    Logs are written to server/logs/audits/audits.jsonl.
    """
    try:
        os.makedirs(AUDITS_DIR, exist_ok=True)
        log_path = os.path.join(AUDITS_DIR, "audits.jsonl")
        
        audit_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "tool_name": tool_name,
            "permissions": permission.to_dict(),
            "initiator": initiator,
            "status": status,  # "approved", "denied", "skipped", "executed", "failed"
            "details": details
        }
        
        with open(log_path, "a") as f:
            f.write(json.dumps(audit_entry) + "\n")
    except Exception as e:
        # Failure Domain resilience: Audit log write failures must not crash runtime
        logger.error(f"[PermissionManager] Audit logging failed: {e}", exc_info=True)
