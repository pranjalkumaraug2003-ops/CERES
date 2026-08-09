import asyncio
import logging
from typing import Any, Callable, Dict, List, Union

logger = logging.getLogger(__name__)

# Subscriber callback type (can be sync or async callable)
SubscriberType = Callable[[Any], Any]

class EventBus:
    def __init__(self):
        self._subscribers: Dict[str, List[SubscriberType]] = {}

    def subscribe(self, event_type: str, callback: SubscriberType) -> None:
        """Subscribe to a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: SubscriberType) -> None:
        """Unsubscribe from a specific event type."""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(callback)
            except ValueError:
                pass

    async def emit(self, event_type: str, data: Any = None) -> None:
        """Asynchronously emit an event to all registered subscribers.
        Each subscriber runs in a separate, isolated task to ensure failures
        do not propagate or block the core query pipeline execution.
        """
        subscribers = self._subscribers.get(event_type, [])
        if not subscribers:
            return

        for callback in subscribers:
            asyncio.create_task(self._run_subscriber_safely(event_type, callback, data))

    async def _run_subscriber_safely(self, event_type: str, callback: SubscriberType, data: Any) -> None:
        """Runs a single subscriber callback in an isolated try-except block."""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(data)
            else:
                callback(data)
        except Exception as e:
            cb_name = getattr(callback, "__name__", str(callback))
            logger.error(
                f"[EventBus] Uncaught exception in subscriber '{cb_name}' "
                f"reacting to event '{event_type}': {e}",
                exc_info=True
            )

# Global singleton Event Bus
event_bus = EventBus()
