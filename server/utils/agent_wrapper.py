"""
agent_wrapper.py — @safe_agent decorator
Catches all exceptions in agent nodes, logs them, and returns a safe
fallback state instead of crashing the LangGraph run.
"""
import functools
import traceback
from datetime import datetime
from server.core.state import CeresState

def safe_agent(agent_name: str):
    """
    Decorator factory for LangGraph agent nodes.
    Usage:  @safe_agent("Orchestrator")
    """
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(state: CeresState) -> dict:
            try:
                return await fn(state)
            except Exception as e:
                tb = traceback.format_exc()
                timestamp = datetime.utcnow().isoformat()
                print(f"[{timestamp}] [{agent_name}] UNHANDLED ERROR: {e}\n{tb}")
                # Return a minimal safe state so LangGraph can continue
                return {
                    "active_agent": agent_name.lower(),
                    "reflection_errors": [f"{agent_name} failed: {str(e)}"],
                    "_next_node": "generate_response",
                }
        return wrapper
    return decorator
