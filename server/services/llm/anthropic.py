"""Anthropic (Claude) provider.

Worth having in the chain because Claude is the most reliable of the hosted
models at *structured tool calling*, which is the one capability CERES cannot
degrade on. Haiku 4.5 is the default: cheapest tier ($1/$5 per Mtok), naturally
concise output — a good fit for spoken narration.

Uses the raw Messages API over httpx rather than the SDK, so this provider adds
no dependency and shares the router's connection pool.
"""

import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

from server.services.llm.base import (
    LLMProvider,
    ProviderError,
    classify_exception,
    classify_http_error,
    get_http_client,
)
from server.services.llm.translate import gemini_contents_to_anthropic, gemini_tools_to_anthropic

logger = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

# Newer Claude models reject temperature/top_p/top_k with a 400. Keep this list
# in sync if you switch `ANTHROPIC_MODEL` to one of them.
_NO_SAMPLING_PARAMS = ("opus-5", "sonnet-5", "fable-5", "mythos-5", "opus-4-7", "opus-4-8")

# max_tokens is REQUIRED by the Messages API (unlike Gemini, where it's optional).
DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    model = "claude-haiku-4-5"
    api_key_env = "ANTHROPIC_API_KEY"

    def _accepts_temperature(self) -> bool:
        return not any(marker in self.model for marker in _NO_SAMPLING_PARAMS)

    async def stream(
        self,
        contents: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.4,
        max_output_tokens: Optional[int] = None,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_output_tokens or DEFAULT_MAX_TOKENS,
            "messages": gemini_contents_to_anthropic(contents),
            "stream": True,
        }
        if system_instruction:
            payload["system"] = system_instruction
        if self._accepts_temperature():
            payload["temperature"] = temperature

        converted_tools = gemini_tools_to_anthropic(tools)
        if converted_tools:
            payload["tools"] = converted_tools

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key or "",
            "anthropic-version": API_VERSION,
        }
        timeout = httpx.Timeout(120.0, connect=10.0, read=120.0)

        # tool_use inputs stream as partial JSON across input_json_delta events.
        active_tool: Optional[Dict[str, str]] = None

        try:
            async with get_http_client().stream(
                "POST", API_URL, headers=headers, json=payload, timeout=timeout
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode(errors="ignore")
                    err = classify_http_error(response.status_code, body, self.name)
                    err.retry_after = _retry_after(response.headers)
                    raise err

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or line.startswith("event:"):
                        continue
                    if not line.startswith("data:"):
                        continue

                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue

                    etype = event.get("type")

                    if etype == "error":
                        message = (event.get("error") or {}).get("message", "unknown error")
                        raise ProviderError(f"{self.name} stream error: {message}", self.name)

                    elif etype == "content_block_start":
                        block = event.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            active_tool = {"name": block.get("name", ""), "json": ""}

                    elif etype == "content_block_delta":
                        delta = event.get("delta") or {}
                        dtype = delta.get("type")
                        if dtype == "text_delta":
                            text = delta.get("text")
                            if text:
                                yield "token", text
                        elif dtype == "input_json_delta" and active_tool is not None:
                            active_tool["json"] += delta.get("partial_json", "")

                    elif etype == "content_block_stop":
                        if active_tool is not None:
                            raw = active_tool["json"].strip()
                            try:
                                args = json.loads(raw) if raw else {}
                            except json.JSONDecodeError:
                                logger.warning(
                                    f"[{self.name}] Bad tool JSON for "
                                    f"'{active_tool['name']}': {raw[:200]}"
                                )
                                args = {}
                            yield "function_call", (
                                active_tool["name"],
                                args if isinstance(args, dict) else {},
                            )
                            active_tool = None

                    elif etype == "message_stop":
                        break

        except (GeneratorExit, KeyboardInterrupt):
            raise
        except Exception as exc:
            raise classify_exception(exc, self.name) from exc


def _retry_after(headers: Any) -> Optional[float]:
    try:
        value = headers.get("retry-after")
        return float(value) if value else None
    except (TypeError, ValueError):
        return None
