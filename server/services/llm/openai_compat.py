"""One adapter for every OpenAI-compatible chat-completions backend.

Groq, OpenRouter, OpenAI, Cerebras, Mistral, and Ollama all expose the same
`/chat/completions` SSE contract, so they differ only in base URL, credential,
and default model. Each becomes a subclass with three class attributes.

This is also how local models arrive later: Ollama serves an OpenAI-compatible
endpoint, so `OllamaProvider` needs no separate implementation — it's just a
different base URL with no API key.
"""

import json
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

from server.services.llm.base import (
    LLMProvider,
    ProviderError,
    classify_exception,
    classify_http_error,
    get_http_client,
)
from server.services.llm.translate import (
    gemini_contents_to_openai,
    gemini_tools_to_openai,
    parse_tool_arguments,
)

logger = logging.getLogger(__name__)


class OpenAICompatProvider(LLMProvider):
    """Base for any provider speaking OpenAI's chat-completions API."""

    base_url: str = ""
    #: Some gateways want extra headers (e.g. OpenRouter attribution).
    extra_headers: Dict[str, str] = {}
    #: Ollama on localhost should give up fast; hosted providers get longer.
    read_timeout: float = 120.0
    connect_timeout: float = 10.0

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _resolve_base_url(self) -> str:
        """Allow `<NAME>_BASE_URL` to override the default endpoint — needed to
        point at a remote Ollama host, a corporate proxy, or a compatible
        gateway without subclassing."""
        env_key = f"{self.name.replace('-', '_').upper()}_BASE_URL"
        return os.getenv(env_key) or self.base_url

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
            "messages": gemini_contents_to_openai(contents, system_instruction),
            "temperature": temperature,
            "stream": True,
        }
        if max_output_tokens is not None:
            payload["max_tokens"] = max_output_tokens

        converted_tools = gemini_tools_to_openai(tools)
        if converted_tools:
            payload["tools"] = converted_tools
            payload["tool_choice"] = "auto"

        url = f"{self._resolve_base_url().rstrip('/')}/chat/completions"
        timeout = httpx.Timeout(self.read_timeout, connect=self.connect_timeout, read=self.read_timeout)

        # Tool calls stream as fragments that must be reassembled by index
        # before we can emit a single well-formed function_call event.
        tool_buffers: Dict[int, Dict[str, str]] = {}

        try:
            async with get_http_client().stream(
                "POST", url, headers=self._headers(), json=payload, timeout=timeout
            ) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode(errors="ignore")
                    err = classify_http_error(response.status_code, body, self.name)
                    err.retry_after = _retry_after(response.headers)
                    raise err

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue  # keep-alive comment
                    if not line.startswith("data:"):
                        continue

                    json_str = line[5:].strip()
                    if json_str == "[DONE]":
                        break

                    try:
                        chunk = json.loads(json_str)
                    except json.JSONDecodeError:
                        continue

                    # Some gateways (notably OpenRouter) deliver upstream errors
                    # inside a 200 stream instead of an HTTP status.
                    if isinstance(chunk.get("error"), dict):
                        message = chunk["error"].get("message", "unknown upstream error")
                        raise ProviderError(f"{self.name} upstream error: {message}", self.name)

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}

                    content = delta.get("content")
                    if content:
                        yield "token", content

                    for fragment in delta.get("tool_calls") or []:
                        index = fragment.get("index", 0)
                        slot = tool_buffers.setdefault(index, {"name": "", "arguments": ""})
                        function = fragment.get("function") or {}
                        if function.get("name"):
                            slot["name"] = function["name"]
                        if function.get("arguments"):
                            slot["arguments"] += function["arguments"]

                # Emit assembled tool calls once the stream is complete.
                for index in sorted(tool_buffers):
                    slot = tool_buffers[index]
                    if slot["name"]:
                        yield "function_call", (
                            slot["name"],
                            parse_tool_arguments(slot["arguments"], slot["name"]),
                        )

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


# ── Concrete providers ───────────────────────────────────────────────────────


class GroqProvider(OpenAICompatProvider):
    """Groq's LPU hardware gives the fastest tokens/sec of any hosted provider,
    which matters more for a voice assistant than raw model quality. Generous
    free tier; Llama 3.3 supports tool calling."""

    name = "groq"
    model = "llama-3.3-70b-versatile"
    api_key_env = "GROQ_API_KEY"
    base_url = "https://api.groq.com/openai/v1"


class OpenRouterProvider(OpenAICompatProvider):
    """Meta-provider: one key reaches most models on the market. Ideal as the
    last hosted tier because it can route around a single vendor's outage."""

    name = "openrouter"
    model = "google/gemini-2.5-flash"
    api_key_env = "OPENROUTER_API_KEY"
    base_url = "https://openrouter.ai/api/v1"
    extra_headers = {"X-Title": "CERES"}


class OpenAIProvider(OpenAICompatProvider):
    name = "openai"
    model = "gpt-4o-mini"
    api_key_env = "OPENAI_API_KEY"
    base_url = "https://api.openai.com/v1"


class CerebrasProvider(OpenAICompatProvider):
    name = "cerebras"
    model = "llama-3.3-70b"
    api_key_env = "CEREBRAS_API_KEY"
    base_url = "https://api.cerebras.ai/v1"


class MistralProvider(OpenAICompatProvider):
    name = "mistral"
    model = "mistral-small-latest"
    api_key_env = "MISTRAL_API_KEY"
    base_url = "https://api.mistral.ai/v1"


class OllamaProvider(OpenAICompatProvider):
    """Local, offline, free — the last resort when the internet is down.

    Needs no API key. Expect slow time-to-first-token on CPU-only hardware
    (prompt prefill is compute-bound), so the timeouts are shorter: if a local
    model can't answer quickly there's no point waiting two minutes for it.
    Prefer a tool-calling-capable model (qwen2.5, llama3.1) — Gemma has no
    native function-calling training and will not drive CERES's tool pipeline.
    """

    name = "ollama"
    model = "qwen2.5:7b"
    api_key_env = None  # no auth on localhost
    base_url = "http://localhost:11434/v1"
    read_timeout = 300.0
    connect_timeout = 2.0  # fail fast when Ollama isn't running

    def availability_error(self) -> Optional[str]:
        # Can't cheaply verify the daemon here; a refused connection surfaces as
        # ProviderConnectionError and opens the circuit, which is good enough.
        return None
