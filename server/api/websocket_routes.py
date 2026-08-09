import json
import logging
import uuid
import asyncio
from typing import Any, Dict
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from server.shared.ws_protocol import WSMessageType, make_ws_message
from server.core.runtime_state import runtime_state
from server.core.audio_coordinator import start_generation, cancel_generation
from server.core.query_handler import handle_query

logger = logging.getLogger(__name__)

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, ws: WebSocket, thread_id: str) -> None:
        await ws.accept()
        self.active_connections[thread_id] = ws

    def attach(self, ws: WebSocket, thread_id: str) -> None:
        self.active_connections[thread_id] = ws

    def disconnect(self, thread_id: str) -> None:
        if thread_id in self.active_connections:
            del self.active_connections[thread_id]

    async def emit(self, thread_id: str, payload: Dict[str, Any]) -> None:
        ws = self.active_connections.get(thread_id)
        if ws:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception:
                # Connection might have died silently
                pass

# WebSocket connections registry
manager = ConnectionManager()

@router.websocket("/ws/chat")
async def websocket_chat(ws: WebSocket) -> None:
    thread_id = str(uuid.uuid4())
    await manager.connect(ws, thread_id)
    runtime_state.websocket_status = "connected"
    current_interaction_id = None

    # Define standardized event sender callback
    async def ws_emit(msg_type: WSMessageType, message: str, agent: str, data: Any = None) -> None:
        enriched = dict(data or {})
        enriched.setdefault("thread_id", thread_id)
        if current_interaction_id:
            enriched.setdefault("interaction_id", current_interaction_id)
        if runtime_state.current_generation:
            enriched.setdefault("gen_id", runtime_state.current_generation)
        payload = make_ws_message(msg_type, message, agent, enriched)
        await manager.emit(thread_id, payload)

    try:
        while True:
            # Clean non-blocking read from WebSocket
            raw = await ws.receive_text()
            payload = json.loads(raw)

            msg_type = payload.get("type")
            if payload.get("interaction_id"):
                current_interaction_id = payload.get("interaction_id")
            
            # 1. Barge-in / Interruption handling
            if msg_type == "interrupt":
                logger.info(f"[Websocket] Interrupt received from client on thread: {thread_id}")
                await cancel_generation(thread_id)
                await ws_emit(WSMessageType.STREAM_CANCELLED, "", "System")
                await ws_emit(WSMessageType.INTERRUPT_ACK, "", "System")
                continue

            # 2. Confirmation response (Approve / Deny payload)
            if msg_type == "confirmation" or payload.get("action") in ("approve", "deny"):
                action_payload = payload.get("data", {})
                if not action_payload and "action" in payload:
                    action_payload = {"action": payload["action"]}
                    
                task_name = f"ceres-{thread_id}"
                await runtime_state.cancel_task(task_name) # Ensure no duplicate tasks run
                
                task = asyncio.create_task(
                    handle_query("", thread_id, ws_emit, approved_payload=action_payload),
                    name=task_name
                )
                runtime_state.register_task(task_name, task)
                task.add_done_callback(lambda _t: runtime_state.remove_task(task_name))
                continue

            # 3. New Query execution
            query = payload.get("query", "").strip()
            if not query:
                continue

            # Re-register socket if thread_id is supplied by client
            if payload.get("thread_id"):
                manager.disconnect(thread_id)
                thread_id = payload["thread_id"]
                manager.attach(ws, thread_id)

            task_name = f"ceres-{thread_id}"
            # Cancel any stale pipeline running on this thread
            await runtime_state.cancel_task(task_name)

            # Assign new generation ID and clear active cache buffers
            start_generation()

            # Execute query processing pipeline in background task to keep socket listener responsive
            task = asyncio.create_task(
                handle_query(query, thread_id, ws_emit),
                name=task_name
            )
            runtime_state.register_task(task_name, task)
            task.add_done_callback(lambda _t: runtime_state.remove_task(task_name))

    except WebSocketDisconnect:
        logger.info(f"[Websocket] Client disconnected from thread {thread_id}")
    except Exception as e:
        logger.error(f"[Websocket] Error in chat socket connection: {e}", exc_info=True)
    finally:
        task_name = f"ceres-{thread_id}"
        await runtime_state.cancel_task(task_name)
        manager.disconnect(thread_id)
        
        # If all sockets closed, update global runtime state status
        if not manager.active_connections:
            runtime_state.websocket_status = "disconnected"
