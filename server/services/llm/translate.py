"""Translators from CERES's canonical Gemini format into other providers' shapes.

CERES speaks Gemini natively — `tool_definitions.py` uses Google's
FunctionDeclaration schema (uppercase "OBJECT"/"STRING" types) and
`query_handler.py` builds `contents` out of `parts`/`functionCall`/
`functionResponse`. Rather than rewrite 20 tool definitions and the
orchestrator, we keep that as the internal format and convert on the way out.

Canonical request shape:
    contents = [{"role": "user"|"model", "parts": [
        {"text": str}
        | {"functionCall":     {"name": str, "args": dict}}
        | {"functionResponse": {"name": str, "response": dict}}
    ]}]
    tools = [{"name": str, "description": str, "parameters": <Gemini schema>}]
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Gemini writes JSON Schema types in caps; everyone else expects lowercase.
_TYPE_MAP = {
    "OBJECT": "object",
    "STRING": "string",
    "INTEGER": "integer",
    "NUMBER": "number",
    "BOOLEAN": "boolean",
    "ARRAY": "array",
    "NULL": "null",
}


def normalize_schema(schema: Any) -> Any:
    """Recursively lowercase Gemini's uppercase `type` values into plain JSON
    Schema. Everything else is passed through untouched."""
    if isinstance(schema, dict):
        out: Dict[str, Any] = {}
        for key, value in schema.items():
            if key == "type" and isinstance(value, str):
                out[key] = _TYPE_MAP.get(value.upper(), value.lower())
            elif key in ("properties", "$defs", "definitions") and isinstance(value, dict):
                out[key] = {k: normalize_schema(v) for k, v in value.items()}
            elif key == "items":
                out[key] = normalize_schema(value)
            elif isinstance(value, (dict, list)):
                out[key] = normalize_schema(value)
            else:
                out[key] = value
        return out
    if isinstance(schema, list):
        return [normalize_schema(item) for item in schema]
    return schema


def _empty_object_schema() -> Dict[str, Any]:
    return {"type": "object", "properties": {}}


# ── OpenAI-compatible (Groq, OpenAI, OpenRouter, Cerebras, Mistral, Ollama) ──


def gemini_tools_to_openai(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    if not tools:
        return None
    converted = []
    for tool in tools:
        params = tool.get("parameters")
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "parameters": normalize_schema(params) if params else _empty_object_schema(),
                },
            }
        )
    return converted


def gemini_contents_to_openai(
    contents: List[Dict[str, Any]],
    system_instruction: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Flatten Gemini contents into OpenAI's chat messages.

    The wrinkle: OpenAI pairs a tool result to its call via `tool_call_id`,
    which Gemini has no concept of. We synthesize ids in encounter order and
    match each functionResponse to the oldest unanswered functionCall — which is
    correct because CERES executes tools strictly in the order it requests them.
    """
    messages: List[Dict[str, Any]] = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})

    pending_ids: List[str] = []
    counter = 0

    for turn in contents:
        role = "assistant" if turn.get("role") == "model" else turn.get("role", "user")
        text_chunks: List[str] = []
        tool_calls: List[Dict[str, Any]] = []
        tool_messages: List[Dict[str, Any]] = []

        for part in turn.get("parts", []) or []:
            if "text" in part:
                if part["text"]:
                    text_chunks.append(part["text"])

            elif "functionCall" in part:
                fc = part["functionCall"] or {}
                call_id = f"call_{counter}"
                counter += 1
                pending_ids.append(call_id)
                tool_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": fc.get("name", ""),
                            "arguments": json.dumps(fc.get("args", {}) or {}, default=str),
                        },
                    }
                )

            elif "functionResponse" in part:
                fr = part["functionResponse"] or {}
                if pending_ids:
                    call_id = pending_ids.pop(0)
                else:
                    # A response with no preceding call (possible after history
                    # truncation). Synthesize an id so the payload stays valid.
                    call_id = f"call_{counter}"
                    counter += 1
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(fr.get("response", {}) or {}, default=str),
                    }
                )

        if tool_calls:
            # OpenAI requires the assistant turn carrying tool_calls to precede
            # the tool results, and content may be null when only calling tools.
            messages.append(
                {
                    "role": "assistant",
                    "content": "\n".join(text_chunks) if text_chunks else None,
                    "tool_calls": tool_calls,
                }
            )
        elif text_chunks:
            messages.append({"role": role, "content": "\n".join(text_chunks)})

        messages.extend(tool_messages)

    if not messages or all(m.get("role") == "system" for m in messages):
        # Every provider rejects a system-only conversation.
        messages.append({"role": "user", "content": "Continue."})

    return messages


# ── Anthropic (Claude) ───────────────────────────────────────────────────────


def gemini_tools_to_anthropic(tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    if not tools:
        return None
    converted = []
    for tool in tools:
        params = tool.get("parameters")
        converted.append(
            {
                "name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "input_schema": normalize_schema(params) if params else _empty_object_schema(),
            }
        )
    return converted


def gemini_contents_to_anthropic(
    contents: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Convert to Anthropic's content-block messages.

    Anthropic differences we handle here:
      - the system prompt is a separate top-level param, not a message
      - tool calls are `tool_use` blocks, results are `tool_result` blocks
      - `tool_result` blocks must live in a *user* turn
      - consecutive same-role turns are merged (Anthropic requires alternation
        in practice, and merging is always safe)
    """
    messages: List[Dict[str, Any]] = []
    pending_ids: List[str] = []
    counter = 0

    for turn in contents:
        role = "assistant" if turn.get("role") == "model" else "user"
        assistant_blocks: List[Dict[str, Any]] = []
        user_blocks: List[Dict[str, Any]] = []

        for part in turn.get("parts", []) or []:
            if "text" in part:
                if part["text"]:
                    (assistant_blocks if role == "assistant" else user_blocks).append(
                        {"type": "text", "text": part["text"]}
                    )

            elif "functionCall" in part:
                fc = part["functionCall"] or {}
                call_id = f"toolu_{counter}"
                counter += 1
                pending_ids.append(call_id)
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": fc.get("name", ""),
                        "input": fc.get("args", {}) or {},
                    }
                )

            elif "functionResponse" in part:
                fr = part["functionResponse"] or {}
                if pending_ids:
                    call_id = pending_ids.pop(0)
                else:
                    call_id = f"toolu_{counter}"
                    counter += 1
                user_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call_id,
                        "content": json.dumps(fr.get("response", {}) or {}, default=str),
                    }
                )

        for target_role, blocks in (("assistant", assistant_blocks), ("user", user_blocks)):
            if not blocks:
                continue
            if messages and messages[-1]["role"] == target_role:
                messages[-1]["content"].extend(blocks)
            else:
                messages.append({"role": target_role, "content": blocks})

    # Anthropic requires the first turn to be `user` and at least one message.
    if not messages:
        messages.append({"role": "user", "content": [{"type": "text", "text": "Continue."}]})
    elif messages[0]["role"] == "assistant":
        messages.insert(0, {"role": "user", "content": [{"type": "text", "text": "Continue."}]})

    return messages


# ── Shared helper for streamed tool-call arguments ───────────────────────────


def parse_tool_arguments(raw: str, tool_name: str = "") -> Dict[str, Any]:
    """OpenAI-style providers stream tool arguments as a JSON *string* built up
    across deltas. Parse defensively — a malformed fragment should degrade to an
    empty dict rather than kill the turn."""
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except json.JSONDecodeError:
        logger.warning(f"[Translate] Could not parse tool arguments for '{tool_name}': {raw[:200]}")
        return {}
