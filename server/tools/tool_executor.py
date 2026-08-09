import asyncio
import logging
from typing import Callable, Any, Dict
from server.core.permissions import get_tool_permission, log_audit
from server.tools.tool_result import ToolResult
from server.core.event_bus import event_bus

logger = logging.getLogger(__name__)

# Registry mapping tool names to executable python callables
_TOOL_REGISTRY: Dict[str, Callable[..., Any]] = {}

def register_tool(name: str, func: Callable[..., Any]) -> None:
    """Registers an executable tool function to the executor registry."""
    _TOOL_REGISTRY[name] = func
    logger.debug(f"[ToolExecutor] Registered tool: {name}")

async def execute_tool(
    tool_name: str,
    args: Dict[str, Any],
    request_id: str,
    initiator: str = "user",
    approved: bool = False
) -> ToolResult:
    """Orchestrates tool execution by checking permissions, enforcing confirmation,
    executing the tool in a safe context, logging audits, and emitting execution events.
    """
    perm = get_tool_permission(tool_name)
    
    # 1. Enforcement of capability confirmation boundaries
    if perm.requires_confirmation and not approved:
        logger.info(f"[ToolExecutor] Action '{tool_name}' blocked. Awaiting user confirmation.")
        log_audit(tool_name, perm, initiator, request_id, "requires_confirmation", f"Args: {args}")
        return ToolResult(
            status="requires_confirmation",
            data={"tool_name": tool_name, "args": args},
            summary=f"Confirmation required before executing: {tool_name}"
        )

    # 2. Resolve executable
    func = _TOOL_REGISTRY.get(tool_name)
    if not func:
        err_msg = f"Tool '{tool_name}' is not registered in the system."
        logger.error(err_msg)
        log_audit(tool_name, perm, initiator, request_id, "failed", err_msg)
        return ToolResult(status="error", data={}, summary="Tool execution failed.", error=err_msg)

    # 3. Execute
    try:
        if asyncio.iscoroutinefunction(func):
            res_data = await func(**args)
        else:
            # Keep sync code isolated in a thread pool to avoid loop starvation
            loop = asyncio.get_event_loop()
            res_data = await loop.run_in_executor(None, lambda: func(**args))

        # Normalize output
        if isinstance(res_data, ToolResult):
            result = res_data
        elif isinstance(res_data, dict) and "status" in res_data:
            result = ToolResult(
                status=res_data.get("status", "success"),
                data=res_data.get("data", {}),
                summary=res_data.get("summary", f"Successfully executed {tool_name}."),
                error=res_data.get("error")
            )
        else:
            result = ToolResult(
                status="success",
                data={"result": res_data},
                summary=f"Successfully completed {tool_name}."
            )
        
        # Log success audit
        log_audit(tool_name, perm, initiator, request_id, "executed", f"Result summary: {result.summary}")
        
        # Emit event
        await event_bus.emit("ToolExecuted", {
            "request_id": request_id,
            "tool_name": tool_name,
            "result": result.to_dict()
        })
        
        return result

    except Exception as e:
        err_str = str(e)
        logger.error(f"[ToolExecutor] Error executing {tool_name}: {e}", exc_info=True)
        log_audit(tool_name, perm, initiator, request_id, "failed", err_str)
        return ToolResult(
            status="error",
            data={},
            summary=f"Failed to execute {tool_name}.",
            error=err_str
        )
