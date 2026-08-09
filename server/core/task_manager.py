import asyncio
import logging
from typing import Set

logger = logging.getLogger(__name__)

# Holds strong references to active background tasks to prevent garbage collection
_active_background_tasks: Set[asyncio.Task] = set()

def spawn_background_task(coro) -> asyncio.Task:
    """Spawns an asynchronous coroutine in the background.
    Keeps a strong reference to the Task to prevent Python's garbage collector
    from destroying it prematurely.
    """
    task = asyncio.create_task(coro)
    _active_background_tasks.add(task)
    
    # Callback to discard the task once finished
    def _done_callback(t: asyncio.Task) -> None:
        _active_background_tasks.discard(t)
        try:
            if not t.cancelled():
                exc = t.exception()
                if exc:
                    logger.error(f"[TaskManager] Background task raised an exception: {exc}", exc_info=exc)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[TaskManager] Error in task callback check: {e}", exc_info=True)

    task.add_done_callback(_done_callback)
    return task
