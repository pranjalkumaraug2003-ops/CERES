import asyncio
from typing import Dict, Optional

class CERESRuntimeState:
    def __init__(self):
        self.current_generation: Optional[str] = None
        self.active_request_id: Optional[str] = None
        self.websocket_status: str = "disconnected"
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.current_mode: str = "native"  # "native" or "legacy"

    def register_task(self, name: str, task: asyncio.Task) -> None:
        """Register a running background task."""
        self.active_tasks[name] = task

    def get_task(self, name: str) -> Optional[asyncio.Task]:
        """Retrieve a task by name."""
        return self.active_tasks.get(name)

    def remove_task(self, name: str) -> Optional[asyncio.Task]:
        """Remove a task from registry."""
        return self.active_tasks.pop(name, None)

    async def cancel_task(self, name: str) -> None:
        """Cancel a running task by name and await its termination."""
        task = self.remove_task(name)
        if task and not task.done():
            task.cancel()
            try:
                # Give it up to 500ms to shut down cleanly
                await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

    async def cancel_all_tasks(self) -> None:
        """Cancel and clean up all active registered tasks."""
        tasks = list(self.active_tasks.values())
        self.active_tasks.clear()
        
        for task in tasks:
            if not task.done():
                task.cancel()
        
        if tasks:
            # Shield and gather to ensure clean teardown of tasks
            await asyncio.gather(*(asyncio.shield(t) for t in tasks if not t.done()), return_exceptions=True)

# Global singleton container
runtime_state = CERESRuntimeState()
