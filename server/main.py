import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import os
# Limit CPU threads to prevent thread contention on high-core CPUs
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"
os.environ["OPENBLAS_NUM_THREADS"] = "4"
os.environ["VECLIB_MAXIMUM_THREADS"] = "4"
os.environ["NUMEXPR_NUM_THREADS"] = "4"

import json
import logging

# Configure root logger to output INFO logs to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

# Optimize PyTorch CPU threads to prevent scheduling thrashing
try:
    import torch
    torch.set_num_threads(4)
    logger.info(f"[Startup] Optimized PyTorch CPU threads to: {torch.get_num_threads()}")
except ImportError:
    pass
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel

# Load environment configurations
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

logger = logging.getLogger(__name__)

# ── Import DB and Utilities ──────────────────────────────────────────────────
from server.services.qdrant_service import init_qdrant
from server.services.postgres_service import init_postgres
from server.services.profile_service import get_profile
from server.services.monitor_service import start_monitor
from server.services.command_history_service import log_command, get_recent_history, init_history_table
from server.utils.cost_tracker import cost_tracker
from server.core.runtime_state import runtime_state

# ── Import Native Services & Routes ──────────────────────────────────────────
from server.services.voice_service import synthesize_sentence, preload_models
from server.services.whisper_service import transcribe_audio
from server.api.websocket_routes import router as chat_router

# Setup FastAPI App
app = FastAPI(title="CERES Gateway")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Include Chat & WebSocket Routes Router
app.include_router(chat_router)

# ── Startup Logic ─────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    try:
        await init_qdrant()
        await init_postgres()
        print("Databases initialized successfully.")
    except Exception as e:
        print(f"Warning: Database initialization failed: {e}")
    
    try:
        profile = await get_profile()
        print(f"User profile loaded: {profile.name}")
    except Exception as e:
        print(f"Warning: Profile load failed: {e}")

    try:
        await init_history_table()
        print("Command history table ready.")
    except Exception as e:
        print(f"Warning: History table init failed: {e}")

    # Preload local Whisper and Kokoro models in the background
    asyncio.create_task(preload_models())

    # Start background intelligence monitor
    async def emit_to_connections(event_type, agent, message, data=None):
        # Route proactively via new WebSocket connections manager
        from server.api.websocket_routes import manager as native_manager
        from server.shared.ws_protocol import make_ws_message, WSMessageType
        # B-2: Resolve the string event_type to the matching WSMessageType;
        # fall back to PROACTIVE_ALERT for unknown/legacy callers.
        try:
            ws_type = WSMessageType(event_type)
        except (ValueError, KeyError):
            ws_type = WSMessageType.PROACTIVE_ALERT
        payload = make_ws_message(ws_type, message, agent, data)
        for thread_id in list(native_manager.active_connections.keys()):
            await native_manager.emit(thread_id, payload)

    start_monitor(emit_to_connections)
    
    from server.services.reminder_service import check_due_reminders
    asyncio.create_task(check_due_reminders(emit_to_connections))

@app.on_event("shutdown")
async def shutdown_event():
    try:
        from server.services.llm import close_http_client as close_llm_client
        from server.services.redis_service import close_redis_client
        from server.services.weather_service import close_weather_client
        from server.services.voice_service import close_tts_client
        await close_llm_client()
        await close_redis_client()
        await close_weather_client()
        await close_tts_client()
        print("Connections closed successfully.")
    except Exception as e:
        print(f"Warning: Cleanup failed on shutdown: {e}")

# ── Direct Resume / Confirmation Route ─────────────────────────────────────────
class ResumeRequest(BaseModel):
    action: str

@app.post("/api/resume/{thread_id}")
async def resume_graph(thread_id: str, request: ResumeRequest):
    """Resume a blocked query execution following user confirmation."""
    from server.api.websocket_routes import manager as native_manager, handle_query
    from server.shared.ws_protocol import make_ws_message
    
    ws = native_manager.active_connections.get(thread_id)
    if not ws:
        return {"status": "error", "message": "Connection session not found"}
        
    async def ws_emit(msg_type, message, agent, data=None):
        payload = make_ws_message(msg_type, message, agent, data)
        await native_manager.emit(thread_id, payload)

    task_name = f"ceres-{thread_id}"
    await runtime_state.cancel_task(task_name)
    
    task = asyncio.create_task(
        handle_query("", thread_id, ws_emit, approved_payload={"action": request.action}),
        name=task_name
    )
    runtime_state.register_task(task_name, task)
    task.add_done_callback(lambda _t: runtime_state.remove_task(task_name))
    return {"status": "ok"}

# ── Health Diagnostic Endpoint ───────────────────────────────────────────────
@app.get("/health")
async def health():
    gemini_status = "configured" if os.getenv("GOOGLE_API_KEY") else "missing"

    # Which providers are configured, and which are benched by the breaker.
    try:
        from server.services.llm import get_router
        llm_status = get_router().status()
    except Exception as e:
        llm_status = {"error": str(e)}

    # Qdrant Check
    try:
        from server.services.qdrant_service import get_qdrant_client
        q_client = get_qdrant_client()
        await q_client.get_collections()
        qdrant_status = "connected"
    except Exception as e:
        qdrant_status = f"failed: {str(e)}"

    # Local TTS Check
    tts_status = "disabled"
    if os.getenv("USE_LOCAL_TTS", "false").lower() == "true":
        try:
            import kokoro
            import soundfile
            tts_status = "ready"
        except ImportError:
            tts_status = "missing_dependencies"
    else:
        tts_status = "configured_cloud"

    # Local STT Check
    whisper_status = "disabled"
    if os.getenv("USE_LOCAL_STT", "false").lower() == "true":
        try:
            import faster_whisper
            whisper_status = "ready"
        except ImportError:
            whisper_status = "missing_dependencies"
    else:
        whisper_status = "configured_cloud"

    return {
        "status": "ok",
        "subsystems": {
            "gemini": gemini_status,
            "qdrant": qdrant_status,
            "tts": tts_status,
            "whisper": whisper_status
        },
        "llm": llm_status,
        "semantic_cache": _semantic_cache_stats()
    }


def _semantic_cache_stats():
    """Hit rate is the number to watch — it maps directly to API calls avoided."""
    try:
        from server.core.semantic_cache import semantic_cache
        return semantic_cache.stats()
    except Exception as e:
        return {"error": str(e)}

# Include routers
from server.api.auth import router as auth_router
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

from server.api.reminders import router as reminders_router
app.include_router(reminders_router, prefix="/api/reminders", tags=["reminders"])

class TTSRequest(BaseModel):
    text: str

@app.post("/api/tts")
async def text_to_speech(request: TTSRequest):
    """Synthesize a text string to WAV audio and return it as binary."""
    import base64
    wav_bytes = await synthesize_sentence(request.text)
    if not wav_bytes:
        return Response(content=b"", media_type="audio/wav", status_code=204)
    return Response(content=wav_bytes, media_type="audio/wav")

@app.post("/api/stt")
async def speech_to_text(audio: UploadFile = File(...)):
    import time as _time
    t0 = _time.time()
    try:
        audio_bytes = await audio.read()
        text = await transcribe_audio(audio_bytes, audio.content_type)
        elapsed = _time.time() - t0
        logger.info(f"[STT] Transcribed in {elapsed:.2f}s: '{text[:80]}'")
        return {"text": text, "latency_ms": round(elapsed * 1000)}
    except Exception as e:
        logger.error(f"[STT] Transcription failed: {e}", exc_info=True)
        return {"error": str(e)}


@app.websocket("/ws/stats")
async def stats_websocket(ws: WebSocket):
    from server.services.system_service import get_system_stats
    await ws.accept()
    try:
        while True:
            stats = await get_system_stats()
            await ws.send_text(json.dumps(stats))
            await asyncio.sleep(5)
    except Exception:
        pass

@app.get("/api/history")
async def get_history(limit: int = 20):
    return await get_recent_history(limit=limit)

@app.get("/api/phone/status")
async def phone_status():
    from server.services.adb_service import is_device_connected, is_adb_available
    adb = is_adb_available()
    connected = await is_device_connected() if adb else False
    return {"adb_installed": adb, "device_connected": connected}

@app.get("/api/stats")
async def get_stats():
    return cost_tracker.summary()
