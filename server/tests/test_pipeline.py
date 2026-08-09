import os
import sys
import asyncio
import logging

# Set platform event loop policy for Windows if needed
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except AttributeError:
        pass

# Ensure server module is in python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("CeresPipelineTest")

from server.core.query_handler import handle_query
from server.shared.ws_protocol import WSMessageType
from server.core.runtime_state import runtime_state

# Track emitted messages for validation
emitted_events = []

async def mock_ws_emit(msg_type: WSMessageType, message: str, agent: str, data=None) -> None:
    event = {
        "type": msg_type,
        "message": message,
        "agent": agent,
        "data": data
    }
    emitted_events.append(event)
    logger.info(f"[Mock WebSocket Event] {msg_type.value.upper()} (from {agent}): {message} | Data: {data}")

async def run_pipeline_tests() -> None:
    logger.info("Starting CERES V2 Pipeline Verification Tests...")
    
    # 1. Test standard conversational reasoning path
    logger.info("=== TEST CASE 1: Chat Reasoning ===")
    emitted_events.clear()
    
    # Ensure we mock the active generation ID in state
    runtime_state.current_generation = "test-gen-123"
    
    await handle_query("Hello, who are you? Keep it very brief.", "test-thread-id", mock_ws_emit)
    
    # Verify events
    types = [e["type"] for e in emitted_events]
    assert WSMessageType.STREAM_START in types, "STREAM_START missing"
    assert WSMessageType.TOKEN_CHUNK in types, "TOKEN_CHUNK missing"
    assert WSMessageType.STREAM_END in types, "STREAM_END missing"
    logger.info("TEST CASE 1 PASSED!")

    # 2. Test Safe Tool Execution (Weather query)
    logger.info("=== TEST CASE 2: Safe Tool execution (Weather) ===")
    emitted_events.clear()
    runtime_state.current_generation = "test-gen-456"
    
    await handle_query("What is the weather in Seattle?", "test-thread-id", mock_ws_emit)
    
    types = [e["type"] for e in emitted_events]
    assert WSMessageType.STREAM_START in types, "STREAM_START missing"
    assert WSMessageType.AGENT_STATE_UPDATE in types, "AGENT_STATE_UPDATE missing"
    assert WSMessageType.STREAM_END in types, "STREAM_END missing"
    logger.info("TEST CASE 2 PASSED!")

    # 3. Test Semantic Caching (Repeat Weather query)
    logger.info("=== TEST CASE 3: Semantic Cache HIT ===")
    emitted_events.clear()
    runtime_state.current_generation = "test-gen-789"
    
    await handle_query("What is the weather in Seattle?", "test-thread-id", mock_ws_emit)
    
    types = [e["type"] for e in emitted_events]
    # In semantic cache hit, tool execution updates should be skipped (instant stream of cache)
    assert WSMessageType.AGENT_STATE_UPDATE not in types, "AGENT_STATE_UPDATE should not run on cache hit"
    assert WSMessageType.STREAM_END in types, "STREAM_END missing"
    logger.info("TEST CASE 3 PASSED!")

    # 4. Test Dangerous Tool Confirmation flow
    logger.info("=== TEST CASE 4: Dangerous Tool Confirmation Block ===")
    emitted_events.clear()
    runtime_state.current_generation = "test-gen-abc"
    
    await handle_query("run command 'echo hello'", "test-thread-id", mock_ws_emit)
    
    types = [e["type"] for e in emitted_events]
    assert WSMessageType.ACTION_REQUIRED in types, "ACTION_REQUIRED missing for dangerous command"
    logger.info("TEST CASE 4 PASSED!")

    logger.info("All CERES V2 Pipeline Verification Tests completed successfully!")

if __name__ == "__main__":
    # Validate API key
    if not os.getenv("GOOGLE_API_KEY"):
        logger.error("GOOGLE_API_KEY environment variable is not configured in .env. Test cannot run.")
        sys.exit(1)
        
    asyncio.run(run_pipeline_tests())
