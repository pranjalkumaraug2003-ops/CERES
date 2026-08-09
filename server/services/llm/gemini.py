"""Google Gemini provider — the primary backend.

Ports the SSE streaming logic from the original `gemini_service.py` and adds
error classification so the router can fail over. No translation needed: Gemini
is the canonical format CERES already speaks.
"""

import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

from server.services.llm.base import (
    LLMProvider,
    classify_exception,
    classify_http_error,
    get_http_client,
)

logger = logging.getLogger(__name__)

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    name = "gemini"
    model = "gemini-2.5-flash"
    api_key_env = "GOOGLE_API_KEY"

    async def stream(
        self,
        contents: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.4,
        max_output_tokens: Optional[int] = None,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        generation_config: Dict[str, Any] = {
            "temperature": temperature,
            # thinkingBudget 0 keeps latency low — CERES is a voice assistant
            # and Flash's reasoning trace would add seconds before first token.
            "thinkingConfig": {"thinkingBudget": 0},
        }
        if max_output_tokens is not None:
            generation_config["maxOutputTokens"] = max_output_tokens

        payload: Dict[str, Any] = {"contents": contents, "generationConfig": generation_config}
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        if tools:
            payload["tools"] = [{"functionDeclarations": tools}]

        # alt=sse forces true token-level flushing instead of buffered chunks.
        url = f"{API_ROOT}/{self.model}:streamGenerateContent?key={self.api_key}&alt=sse"
        timeout = httpx.Timeout(120.0, connect=10.0, read=120.0)

        try:
            async with get_http_client().stream(
                "POST", url, headers={"Content-Type": "application/json"}, json=payload, timeout=timeout
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

                    if line.startswith("data: "):
                        json_str = line[6:]
                    elif line.startswith("data:"):
                        json_str = line[5:]
                    else:
                        continue

                    if json_str.strip() == "[DONE]":
                        break

                    try:
                        chunk = json.loads(json_str)
                    except json.JSONDecodeError:
                        continue  # partial SSE fragment

                    candidates = chunk.get("candidates") or []
                    if not candidates:
                        continue

                    for part in candidates[0].get("content", {}).get("parts", []) or []:
                        if "text" in part and part["text"]:
                            yield "token", part["text"]
                        elif "functionCall" in part:
                            fc = part["functionCall"] or {}
                            yield "function_call", (fc.get("name"), fc.get("args", {}) or {})

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


class GeminiProProvider(GeminiProvider):
    """Gemini Pro — slower and pricier, but a useful quality tier. Handy as a
    fallback for Flash since it uses a separate model quota."""

    name = "gemini-pro"
    model = "gemini-2.5-pro"


def gemini_model_from_env(default: str = "gemini-2.5-flash") -> str:
    return os.getenv("GEMINI_MODEL", default)
