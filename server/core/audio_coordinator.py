import uuid
import logging
from server.core.runtime_state import runtime_state
from server.core.event_bus import event_bus

logger = logging.getLogger(__name__)

def start_generation() -> str:
    """Starts a new speech generation cycle by creating a unique generation ID.
    Updating the runtime state invalidates any previous active playback.
    """
    gen_id = str(uuid.uuid4())
    runtime_state.current_generation = gen_id
    logger.info(f"[AudioCoordinator] Registered new generation ID: {gen_id}")
    return gen_id

async def cancel_generation(thread_id: str) -> None:
    """Invalidates the current generation ID and forcefully terminates running pipeline tasks.
    Triggers SpeechInterrupted event and clean socket cancel flows.
    """
    current_gen = runtime_state.current_generation
    runtime_state.current_generation = None  # Instantly invalidates running synthesis workers
    
    # Cancel the running pipeline task mapped to the WebSocket connection thread ID
    pipeline_task_name = f"ceres-{thread_id}"
    await runtime_state.cancel_task(pipeline_task_name)
    
    if current_gen:
        logger.info(f"[AudioCoordinator] Cancelled active generation: {current_gen}")
        # Emit observer event
        await event_bus.emit("SpeechInterrupted", {"gen_id": current_gen})
