import asyncio
import logging
import uuid
import time
from typing import Callable, Any, Dict, Optional, List

from server.core.runtime_state import runtime_state
from server.core.event_bus import event_bus
from server.core.tracer import Trace
from server.core.context_manager import build_context
from server.core.security import detect_and_sanitize_injection
from server.core.semantic_cache import bucket_for_tool, semantic_cache
from server.core.streaming_pipeline import StreamingPipeline
from server.core.task_manager import spawn_background_task
from server.core.narration_engine import narrate

from server.services.llm import get_router
from server.services.command_history_service import log_command
from server.services.memory_service import run_memory_extraction
from server.services.local_router_service import check_reflex, classify_intent
from server.services.redis_service import get_session_history, add_session_turn

from server.tools.tool_executor import execute_tool
from server.tools.tool_definitions import TOOL_DECLARATIONS
from server.shared.ws_protocol import WSMessageType

logger = logging.getLogger(__name__)

# Multi-provider router with automatic failover (Gemini -> Groq -> ... ).
# Same generate_stream() contract the old GeminiService exposed.
gemini_client = get_router()

# Global registry for active queries awaiting confirmation
_pending_confirmations: Dict[str, Dict[str, Any]] = {}

SYSTEM_INSTRUCTION = (
    "You are CERES, a calm, concise, direct, and confident personal AI assistant.\n"
    "Respond in short, natural spoken sentences. Avoid markdown syntax in speech outputs.\n"
    "When you run a tool, summarize its results briefly and confirm actions completion naturally."
)

# Separate, much tighter system prompt ONLY for narrating tool results.
# This is the single biggest latency optimization: forces 1-3 sentence responses
# instead of 10-20 sentence explanations.
NARRATION_INSTRUCTION = (
    "You are CERES, a voice assistant. Narrate the tool result to the user.\n"
    "STRICT RULES:\n"
    "- Respond in 1 to 3 SHORT spoken sentences MAXIMUM.\n"
    "- State the answer IMMEDIATELY. Do not explain methodology or process.\n"
    "- Do NOT use markdown, bullet points, lists, or any formatting.\n"
    "- Do NOT add caveats, disclaimers, or suggestions unless the data shows an error.\n"
    "- Numbers should be spoken naturally (e.g. 'thirty two degrees' not '32°C').\n"
    "- If the tool returned an error, say so briefly and suggest what the user can try.\n"
    "Example good response: 'It is currently thirty two degrees and partly cloudy in Delhi, with humidity at forty five percent.'"
)


def prune_tools(intent: str) -> Optional[List[Dict[str, Any]]]:
    """Prunes tool declarations based on the identified intent to decrease Gemini latency."""
    if intent == "general" or intent is None:
        return TOOL_DECLARATIONS
        
    intent_to_tool_names = {
        "weather":  ["get_weather"],
        "music":    ["media_control"],
        "maps":     ["open_maps", "search_web", "open_url"],
        "calendar": ["get_calendar_events", "create_reminder"],
        "code":     ["run_shell_command"],
        "gmail":    ["send_email", "get_unread_emails"],
        "finance":  ["get_exchange_rate", "get_gold_price", "get_crypto_price"],
        "system":   ["get_system_stats", "take_screenshot", "lock_pc", "open_app", "close_application", "delete_file"]
    }
    
    allowed_names = intent_to_tool_names.get(intent)
    if not allowed_names:
        return None # Return None to omit tools entirely for purely conversational intents!
        
    # Filter TOOL_DECLARATIONS
    pruned = [tool for tool in TOOL_DECLARATIONS if tool["name"] in allowed_names]
    return pruned


async def handle_query(
    query: str,
    thread_id: str,
    ws_emit: Callable[[WSMessageType, str, str, Any], Any],
    approved_payload: Optional[Dict[str, Any]] = None
) -> None:
    """Central orchestrator pipeline that runs queries from input to streaming audio output.
    Ensures tracer tracking, context sanitization, cache verification, tool execution,
    and event emissions.
    
    CRITICAL: Every code path MUST clean up runtime state in `finally` blocks.
    """
    request_id = str(uuid.uuid4())
    generation_id = runtime_state.current_generation or str(uuid.uuid4())
    
    trace = Trace(request_id=request_id)
    trace.metadata["query"] = query
    trace.metadata["thread_id"] = thread_id
    trace.metadata["generation_id"] = generation_id

    logger.info(
        f"[QueryHandler] === Request {request_id} === "
        f"query='{query[:80]}' thread={thread_id} gen={generation_id[:8]}"
    )

    # ── 1. Resume Tool Confirmation ──
    if approved_payload:
        logger.info(f"[QueryHandler] Resuming pending tool execution for thread: {thread_id}")
        try:
            await _resume_tool_execution(approved_payload, thread_id, ws_emit, trace, generation_id)
        except Exception as e:
            logger.error(f"[QueryHandler] Resume failed: {e}", exc_info=True)
            await ws_emit(WSMessageType.ERROR, f"Resume failed: {e}", "System")
        finally:
            _cleanup_generation_state(request_id, trace)
        return

    # Emit QueryReceived
    await event_bus.emit("QueryReceived", {"query": query, "request_id": request_id})

    # Reflex Layer Check (runs before cache and inference)
    reflex_res = check_reflex(query)
    if reflex_res:
        if isinstance(reflex_res, dict) and reflex_res.get("type") == "tool":
            tool_name = reflex_res["tool_name"]
            tool_args = reflex_res["args"]
            trace.metadata["intent"] = tool_name
            trace.metadata["tool_name"] = tool_name
            
            logger.info(f"[QueryHandler] Short-circuit reflex tool: {tool_name} with args: {tool_args}")
            await ws_emit(WSMessageType.AGENT_STATE_UPDATE, f"Running tool: {tool_name}...", "System")
            
            with trace.span("tool_execution", tool_name=tool_name):
                result = await execute_tool(tool_name, tool_args, request_id, approved=False)
                
            trace.metadata["tool_status"] = result.status
            
            await _narrate_tool_result(
                result=result,
                tool_name=tool_name,
                contents=[],
                envelope=None,
                ws_emit=ws_emit,
                trace=trace,
                generation_id=generation_id,
                thread_id=thread_id,
                query=query
            )
            return

        reflex_intent = reflex_res
        trace.metadata["intent"] = reflex_intent
        if reflex_intent == "stop":
            await cancel_generation(thread_id)
            await ws_emit(WSMessageType.STREAM_CANCELLED, "", "System")
            await ws_emit(WSMessageType.INTERRUPT_ACK, "", "System")
            _cleanup_generation_state(request_id, trace)
            return
            
        if reflex_intent == "greeting":
            reflex_text = "Hello! How can I help you today?"
        elif reflex_intent == "thanks":
            reflex_text = "You're welcome! Let me know if you need anything else."
        elif reflex_intent == "time":
            from datetime import datetime
            reflex_text = f"The current time is {datetime.now().strftime('%I:%M %p')}."
        else:
            reflex_text = "Sure, how can I assist?"
            
        await ws_emit(WSMessageType.STREAM_START, "CERES is thinking...", "System", {"thread_id": thread_id})
        pipeline = StreamingPipeline(generation_id, ws_emit)
        
        async def _reflex_token_generator():
            words = reflex_text.split(" ")
            for i, word in enumerate(words):
                yield word + (" " if i < len(words)-1 else "")
                await asyncio.sleep(0.02)
                
        with trace.span("reflex_delivery"):
            full_text = await pipeline.consume_token_stream(_reflex_token_generator())
        await ws_emit(WSMessageType.STREAM_END, "Complete.", "System")
        
        trace.metadata["total_perceived"] = time.time() - trace.start_time
        spawn_background_task(log_command(thread_id, query, full_text, reflex_intent, "REFLEX", trace.metadata["total_perceived"]))
        await event_bus.emit("QueryCompleted", {"request_id": request_id, "status": "completed"})
        _cleanup_generation_state(request_id, trace)
        return

    try:
        # ── 2. Semantic Cache Check ──
        with trace.span("semantic_cache_check"):
            cached_response = semantic_cache.get(query)
            if cached_response:
                logger.info(f"[QueryHandler] Serving from semantic cache.")
                trace.metadata["cache_hit"] = True
                trace.metadata["intent"] = "cache_hit"
                
                # Simulate streaming of cached response tokens
                pipeline = StreamingPipeline(generation_id, ws_emit)
                
                async def _cached_token_generator():
                    words = cached_response.split(" ")
                    for i, word in enumerate(words):
                        yield word + (" " if i < len(words)-1 else "")
                        await asyncio.sleep(0.02)
                        
                await ws_emit(WSMessageType.STREAM_START, "CERES is thinking...", "System", {"thread_id": thread_id})
                with trace.span("cache_delivery"):
                    full_text = await pipeline.consume_token_stream(_cached_token_generator())
                
                await ws_emit(WSMessageType.STREAM_END, "Complete.", "System")
                
                spawn_background_task(log_command(thread_id, query, full_text, "semantic_cache", "CACHE", 0.0))
                await event_bus.emit("QueryCompleted", {"request_id": request_id, "status": "cache_hit"})
                return

        # Sanitize query first to ensure context building uses the sanitized query
        sanitized_query, injection_detected = detect_and_sanitize_injection(query)
        if injection_detected:
            logger.warning("[QueryHandler] Sanitized prompt injection in user query.")
            trace.metadata["injection_detected"] = True

        # ── 3. Build Context & Route Intent Concurrently (using explicit task scheduling) ──
        async def run_routing():
            with trace.span("intent_routing"):
                return await classify_intent(sanitized_query)

        async def run_context():
            with trace.span("context_building"):
                return await build_context(sanitized_query, request_id)

        routing_task = asyncio.create_task(run_routing())
        context_task = asyncio.create_task(run_context())

        router_res, envelope = await asyncio.gather(routing_task, context_task)

        intent = router_res["intent"]
        confidence = router_res["confidence"]
        trace.metadata["intent"] = intent

        # ── 4. Early Tool Pruning ──
        pruned_tools = prune_tools(intent)

        # ── 5. Setup Gemini Request with History ──
        history_turns = await get_session_history(thread_id, limit=5)
        contents = []
        for turn in history_turns:
            contents.append({
                "role": turn["role"],
                "parts": [{"text": turn["text"]}]
            })

        # Append current user prompt with context envelope
        contents.append({
            "role": "user",
            "parts": [
                {"text": f"Context Information:\n{envelope.get_tool_calling_context()}\n\nUser Query: {sanitized_query}"}
            ]
        })

        await ws_emit(WSMessageType.STREAM_START, "CERES is thinking...", "System", {"thread_id": thread_id})

        # ── 6. Run LLM Tool Decision ──
        tool_name: Optional[str] = None
        tool_args: Dict[str, Any] = {}
        text_tokens: List[str] = []

        with trace.span("gemini_tool_decision"):
            try:
                # buffered=True: these tokens are collected into text_tokens and
                # only streamed later, so nothing has reached the user yet. That
                # lets the router fail over even on a late failure, with no risk
                # of duplicating spoken output.
                generator = gemini_client.generate_stream(
                    contents=contents,
                    system_instruction=SYSTEM_INSTRUCTION,
                    tools=pruned_tools,
                    buffered=True
                )
                
                async for event_type, data in generator:
                    if event_type == "error":
                        await ws_emit(WSMessageType.ERROR, data, "System")
                        trace.metadata["intent"] = "llm_error"
                        trace.finish(error=data)
                        return
                    elif event_type == "token":
                        text_tokens.append(data)
                    elif event_type == "function_call":
                        tool_name, tool_args = data
                        break
            except Exception as e:
                logger.error(f"[QueryHandler] Gemini request failed: {e}", exc_info=True)
                await ws_emit(WSMessageType.ERROR, f"Reasoning engine failed: {e}", "System")
                trace.metadata["intent"] = "llm_exception"
                trace.finish(error=str(e))
                return

        trace.metadata["intent"] = tool_name if tool_name else intent
        trace.metadata["tool_name"] = tool_name

        # ── 7. Execute Tool Or Handle Confirmation ──
        if tool_name:
            logger.info(f"[QueryHandler] Gemini requested tool: {tool_name} with args: {tool_args}")
            await ws_emit(WSMessageType.AGENT_STATE_UPDATE, f"Running tool: {tool_name}...", "System")
            
            with trace.span("tool_execution", tool_name=tool_name):
                result = await execute_tool(tool_name, tool_args, request_id, approved=False)

            trace.metadata["tool_status"] = result.status

            if result.status == "requires_confirmation":
                # Store pending details to resume after user confirmation
                _pending_confirmations[thread_id] = {
                    "tool_name": tool_name,
                    "args": tool_args,
                    "query": query,
                    "contents": contents,
                    "envelope": envelope,
                    "request_id": request_id,
                    "trace": trace
                }
                await ws_emit(
                    WSMessageType.ACTION_REQUIRED,
                    message=result.summary,
                    agent="System",
                    data={
                        "thread_id": thread_id,
                        "action_payload": {"tool": tool_name, "args": tool_args}
                    }
                )
                # NOTE: Do NOT clean up generation state here — we're waiting for confirmation
                return
                
            # Tool executed directly: narrate the output
            await _narrate_tool_result(result, tool_name, contents, envelope, ws_emit, trace, generation_id, thread_id, query)
        else:
            # Conversational fallback: stream text responses directly to client
            full_text = "".join(text_tokens)

            # Only cache successful conversational responses (never tool-related)
            if full_text and len(full_text.strip()) > 20:
                semantic_cache.set(query, full_text, "help")
            
            pipeline = StreamingPipeline(generation_id, ws_emit)
            
            async def _token_generator():
                for t in text_tokens:
                    yield t
                    
            with trace.span("conversational_delivery"):
                await pipeline.consume_token_stream(_token_generator())
            await ws_emit(WSMessageType.STREAM_END, "Complete.", "System")
            
            trace.metadata["total_perceived"] = time.time() - trace.start_time
            
            spawn_background_task(log_command(thread_id, query, full_text, "conversation", "GEMINI", trace.metadata["total_perceived"]))
            spawn_background_task(run_memory_extraction(thread_id, query, full_text))
            spawn_background_task(add_session_turn(thread_id, query, full_text))
            await event_bus.emit("QueryCompleted", {"request_id": request_id, "status": "completed"})

    except asyncio.CancelledError:
        logger.info(f"[QueryHandler] Request {request_id} was cancelled (barge-in or disconnect).")
        trace.metadata["cancelled"] = True
    except Exception as e:
        logger.error(f"[QueryHandler] Unhandled exception in request {request_id}: {e}", exc_info=True)
        try:
            await ws_emit(WSMessageType.ERROR, f"Internal error: {e}", "System")
        except Exception:
            pass  # WebSocket may already be dead
        trace.metadata["unhandled_error"] = str(e)
    finally:
        # CRITICAL: Always clean up generation state regardless of success/failure/cancel.
        # This prevents stale state from leaking into subsequent requests.
        _cleanup_generation_state(request_id, trace)


def _cleanup_generation_state(request_id: str, trace: Trace) -> None:
    """Guaranteed cleanup after every request lifecycle.
    Resets generation state so subsequent queries start fresh.
    """
    try:
        # Finalize trace if not already done
        if trace.end_time == 0:
            trace.metadata["total_perceived"] = time.time() - trace.start_time
            trace.finish()
    except Exception as e:
        logger.error(f"[QueryHandler] Trace finalization failed: {e}", exc_info=True)

    logger.debug(f"[QueryHandler] Cleanup complete for request: {request_id}")


async def _resume_tool_execution(
    approved_payload: Dict[str, Any],
    thread_id: str,
    ws_emit: Callable[[WSMessageType, str, str, Any], Any],
    trace: Trace,
    generation_id: str
) -> None:
    """Executes a previously blocked tool when approved by the user."""
    pending = _pending_confirmations.pop(thread_id, None)
    if not pending:
        logger.warning(f"[QueryHandler] No pending tool confirmation found for thread: {thread_id}")
        await ws_emit(WSMessageType.ERROR, "No pending action found to resume.", "System")
        return

    tool_name = pending["tool_name"]
    tool_args = pending["args"]
    query = pending["query"]
    contents = pending["contents"]
    envelope = pending["envelope"]
    request_id = pending["request_id"]
    pending_trace = pending["trace"]

    action = approved_payload.get("action")
    
    await ws_emit(WSMessageType.STREAM_START, "Resuming action...", "System", {"thread_id": thread_id})

    if action == "approve":
        logger.info(f"[QueryHandler] Action approved. Executing tool: {tool_name}")
        await ws_emit(WSMessageType.AGENT_STATE_UPDATE, f"Executing approved action: {tool_name}...", "System")
        
        with pending_trace.span("tool_execution_resumed", tool_name=tool_name):
            result = await execute_tool(tool_name, tool_args, request_id, approved=True)
            
        await _narrate_tool_result(result, tool_name, contents, envelope, ws_emit, pending_trace, generation_id, thread_id, query)
    else:
        # User denied
        logger.info(f"[QueryHandler] Action denied for tool: {tool_name}")
        await ws_emit(WSMessageType.AGENT_STATE_UPDATE, "Action cancelled by user.", "System")
        
        contents.append({
            "role": "model",
            "parts": [{"functionCall": {"name": tool_name, "args": tool_args}}]
        })
        contents.append({
            "role": "user",
            "parts": [{"functionResponse": {"name": tool_name, "response": {"status": "denied", "error": "User denied execution"}}}]
        })
        
        pipeline = StreamingPipeline(generation_id, ws_emit)
        generator = gemini_client.generate_stream(
            contents=contents,
            system_instruction=SYSTEM_INSTRUCTION
        )
        
        async def _refusal_token_generator():
            async for event_type, data in generator:
                if event_type == "token":
                    yield data
                    
        full_text = await pipeline.consume_token_stream(_refusal_token_generator())
        await ws_emit(WSMessageType.STREAM_END, "Complete.", "System")
        
        pending_trace.metadata["total_perceived"] = time.time() - pending_trace.start_time
        
        spawn_background_task(log_command(thread_id, query, full_text, "conversation", "GEMINI", pending_trace.metadata["total_perceived"]))
        spawn_background_task(add_session_turn(thread_id, query, full_text))
        await event_bus.emit("QueryCompleted", {"request_id": request_id, "status": "denied"})
        pending_trace.finish()


async def _narrate_tool_result(
    result: Any,
    tool_name: str,
    contents: List[Dict[str, Any]],
    envelope: Any,
    ws_emit: Callable[[WSMessageType, str, str, Any], Any],
    trace: Trace,
    generation_id: str,
    thread_id: str,
    query: str
) -> None:
    """Takes a ToolResult, sends it back into the Gemini history, and streams the
    response narration to the client.
    
    PERFORMANCE: Tries template narration first (0ms). If unsupported, falls back to
    stripped-down Gemini prompt with maxOutputTokens=150, temperature=0.2.
    """
    # 1. Attempt template narration first
    template_text = narrate(tool_name, result)
    
    if template_text is not None:
        logger.info(f"[QueryHandler] Narrating tool '{tool_name}' via template: '{template_text}'")
        await ws_emit(WSMessageType.AGENT_STATE_UPDATE, "Synthesizing answer...", "System")
        
        pipeline = StreamingPipeline(generation_id, ws_emit)
        
        async def _template_token_generator():
            words = template_text.split(" ")
            for i, word in enumerate(words):
                yield word + (" " if i < len(words)-1 else "")
                await asyncio.sleep(0.02)
                
        try:
            with trace.span("template_delivery"):
                full_text = await pipeline.consume_token_stream(_template_token_generator())
        except Exception as e:
            logger.error(f"[QueryHandler] Template narration streaming failed: {e}", exc_info=True)
            await ws_emit(WSMessageType.ERROR, f"Narration streaming failed: {e}", "System")
            trace.finish(error=str(e))
            return
            
        engine_type = "TEMPLATE"
    else:
        # 2. Fallback to Gemini Narration if no template matches
        logger.info(f"[QueryHandler] No template matches '{tool_name}'. Falling back to Gemini narration.")
        narration_contents = [
            {"role": "user", "parts": [{"text": f"User asked: {query}"}]},
            {"role": "model", "parts": [{"functionCall": {"name": tool_name, "args": result.data}}]},
            {"role": "user", "parts": [{"functionResponse": {"name": tool_name, "response": result.to_dict()}}]},
        ]

        await ws_emit(WSMessageType.AGENT_STATE_UPDATE, "Synthesizing answer...", "System")

        with trace.span("gemini_narration"):
            try:
                generator = gemini_client.generate_stream(
                    contents=narration_contents,
                    system_instruction=NARRATION_INSTRUCTION,
                    temperature=0.2,           # Low temp = less rambling, more deterministic
                    max_output_tokens=150      # Hard cap: ~1-3 sentences
                )
                
                pipeline = StreamingPipeline(generation_id, ws_emit)
                
                async def _narration_token_generator():
                    async for event_type, data in generator:
                        if event_type == "token":
                            yield data
                            
                with trace.span("narration_delivery"):
                    full_text = await pipeline.consume_token_stream(_narration_token_generator())
            except Exception as e:
                logger.error(f"[QueryHandler] Gemini narration failed: {e}", exc_info=True)
                await ws_emit(WSMessageType.ERROR, f"Narration synthesis failed: {e}", "System")
                trace.finish(error=str(e))
                return
        
        engine_type = "GEMINI"

    await ws_emit(WSMessageType.STREAM_END, "Complete.", "System")
    
    # Track perceived latency
    trace.metadata["total_perceived"] = time.time() - trace.start_time
    trace.metadata["tool_result_status"] = result.status
    
    # Store result in semantic cache ONLY if successful. bucket_for_tool routes
    # side-effecting tools to a never-cached bucket — otherwise a cached
    # "Opening Notepad now." would be replayed on the next ask WITHOUT actually
    # opening anything, since the cache is checked before tool execution.
    if result.status == "success" and full_text:
        semantic_cache.set(query, full_text, bucket_for_tool(tool_name))

    # Trigger background operations
    spawn_background_task(log_command(thread_id, query, full_text, tool_name, engine_type, trace.metadata["total_perceived"]))
    spawn_background_task(run_memory_extraction(thread_id, query, full_text))
    spawn_background_task(add_session_turn(thread_id, query, full_text))
    await event_bus.emit("QueryCompleted", {"request_id": trace.request_id, "status": "completed"})
    trace.finish()
