from enum import Enum
from typing import Any, Dict, Optional
import time

class WSMessageType(str, Enum):
    STREAM_START = "stream_start"
    TOKEN_CHUNK = "token_chunk"
    TTS_START = "tts_start"
    TTS_CHUNK = "tts_chunk"
    STREAM_END = "stream_end"
    STREAM_CANCELLED = "stream_cancelled"
    INTERRUPT_ACK = "interrupt_ack"
    ACTION_REQUIRED = "action_required"
    AGENT_STATE_UPDATE = "agent_state_update"
    PROACTIVE_ALERT = "proactive_alert"
    ERROR = "stream_error"
    INTERRUPT = "interrupt"
    CONFIRMATION = "confirmation"

def make_ws_message(
    msg_type: WSMessageType,
    message: str = "",
    agent: str = "System",
    data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Helper function to create a standardized WebSocket message payload.
    Ensures structural conformity to prevent backend-frontend protocol drift.
    """
    payload_data = data or {}
    return {
        "type": msg_type.value,
        "agent": agent,
        "message": message,
        "timestamp": time.time(),
        "interaction_id": payload_data.get("interaction_id"),
        "data": payload_data
    }
