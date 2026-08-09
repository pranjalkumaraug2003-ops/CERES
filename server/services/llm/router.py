"""Failover router — tries providers in order until one answers.

Drop-in replacement for `GeminiService`: same `generate_stream()` signature and
the same ("token" | "function_call" | "error") event contract, so callers are
unaware that failover exists.

Chain is configured by LLM_PROVIDER_CHAIN (comma-separated, highest priority
first), default "gemini,groq,openrouter". Providers with no credential are
skipped silently, so an unconfigured chain entry costs nothing.

Two guarantees worth understanding:

1. **A failed provider gets benched.** The circuit breaker keeps a dead
   provider out of the path for a cooling-off period instead of paying its
   timeout on every single request. Cooldown doubles on repeated failure.

2. **Failover never duplicates speech.** Once a token has been handed
   downstream, CERES has already started speaking it — restarting on another
   provider would repeat audio. So mid-stream failures fail loudly rather than
   silently re-answering. Callers that buffer the whole response before
   speaking (the tool-decision call) pass `buffered=True` to get full failover
   coverage at no cost, since they weren't streaming live anyway.
"""

import asyncio
import logging
import os
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from server.services.llm.anthropic import AnthropicProvider
from server.services.llm.base import LLMProvider, ProviderError, ProviderUnavailable
from server.services.llm.gemini import GeminiProProvider, GeminiProvider
from server.services.llm.openai_compat import (
    CerebrasProvider,
    GroqProvider,
    MistralProvider,
    OllamaProvider,
    OpenAIProvider,
    OpenRouterProvider,
)

logger = logging.getLogger(__name__)

PROVIDER_REGISTRY = {
    "gemini": GeminiProvider,
    "gemini-pro": GeminiProProvider,
    "groq": GroqProvider,
    "openrouter": OpenRouterProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "cerebras": CerebrasProvider,
    "mistral": MistralProvider,
    "ollama": OllamaProvider,
}

DEFAULT_CHAIN = "gemini,groq,openrouter"

#: Per-provider model override, e.g. GROQ_MODEL=llama-3.1-8b-instant
MODEL_ENV_TEMPLATE = "{}_MODEL"


class LLMRouter:
    def __init__(self, chain: Optional[List[str]] = None):
        self.providers: List[LLMProvider] = []
        self._build_chain(chain or self._chain_from_env())

    # ── setup ────────────────────────────────────────────────────────────────

    @staticmethod
    def _chain_from_env() -> List[str]:
        raw = os.getenv("LLM_PROVIDER_CHAIN", DEFAULT_CHAIN)
        return [name.strip().lower() for name in raw.split(",") if name.strip()]

    def _build_chain(self, names: List[str]) -> None:
        for name in names:
            cls = PROVIDER_REGISTRY.get(name)
            if cls is None:
                logger.warning(
                    f"[LLMRouter] Unknown provider '{name}' in LLM_PROVIDER_CHAIN. "
                    f"Known: {', '.join(sorted(PROVIDER_REGISTRY))}"
                )
                continue
            env_key = MODEL_ENV_TEMPLATE.format(name.replace("-", "_").upper())
            self.providers.append(cls(model=os.getenv(env_key) or None))

        if not self.providers:
            logger.error("[LLMRouter] No usable providers configured — every request will fail.")
            return

        configured = [p for p in self.providers if p.availability_error() is None]
        logger.info(
            f"[LLMRouter] Chain: {' -> '.join(p.name for p in self.providers)} "
            f"({len(configured)}/{len(self.providers)} have credentials)"
        )
        for provider in self.providers:
            reason = provider.availability_error()
            if reason:
                logger.warning(f"[LLMRouter] '{provider.name}' will be skipped: {reason}")

    def _eligible(self) -> List[LLMProvider]:
        """Providers with credentials and a closed circuit, in priority order."""
        eligible = []
        for provider in self.providers:
            reason = provider.availability_error()
            if reason:
                continue
            if provider.breaker.is_open:
                logger.debug(
                    f"[LLMRouter] Skipping '{provider.name}' — circuit open for "
                    f"{provider.breaker.seconds_remaining:.0f}s more."
                )
                continue
            eligible.append(provider)
        return eligible

    def _eligible_or_revived(self) -> List[LLMProvider]:
        """As `_eligible`, but if every provider is benched, retry the one whose
        cooldown expires soonest. Being slow beats being dead — a total outage
        of the assistant is worse than one extra doomed request."""
        eligible = self._eligible()
        if eligible:
            return eligible

        candidates = [p for p in self.providers if p.availability_error() is None]
        if not candidates:
            return []

        soonest = min(candidates, key=lambda p: p.breaker.seconds_remaining)
        logger.warning(
            f"[LLMRouter] All providers benched; force-retrying '{soonest.name}' "
            f"({soonest.breaker.seconds_remaining:.0f}s remained on its cooldown)."
        )
        return [soonest]

    # ── main entry point ─────────────────────────────────────────────────────

    async def generate_stream(
        self,
        contents: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.4,
        max_output_tokens: Optional[int] = None,
        buffered: bool = False,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        """Stream from the first provider that succeeds.

        Signature matches the old `GeminiService.generate_stream` exactly, plus
        `buffered`. Set `buffered=True` when the caller collects the full
        response before using it — the router then withholds output until a
        provider completes, making failover safe even on a late failure.
        """
        providers = self._eligible_or_revived()
        if not providers:
            message = self._no_providers_message()
            logger.error(f"[LLMRouter] {message}")
            yield "error", message
            return

        failures: List[str] = []

        for index, provider in enumerate(providers):
            emitted = 0
            buffer: List[Tuple[str, Any]] = []
            is_last = index == len(providers) - 1

            try:
                async for event in provider.stream(
                    contents=contents,
                    system_instruction=system_instruction,
                    tools=tools,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                ):
                    if buffered:
                        buffer.append(event)
                    else:
                        emitted += 1
                        yield event

                # Completed without raising — this provider served the request.
                provider.breaker.record_success()
                if index > 0:
                    logger.info(f"[LLMRouter] Served by fallback provider '{provider.name}'.")
                if buffered:
                    for event in buffer:
                        yield event
                return

            except (GeneratorExit, asyncio.CancelledError):
                # NOT a provider failure. The consumer stopped reading — which
                # `query_handler` does deliberately, breaking out of the loop the
                # moment it sees a function_call. Treating this as an outage
                # would bench a perfectly healthy provider on every tool call.
                raise

            except ProviderError as err:
                provider.breaker.record_failure(err)
                failures.append(f"{provider.name}: {err.message[:160]}")

                if not err.should_failover:
                    # A 400 means our payload is malformed; the next provider
                    # would reject it identically. Surface it instead.
                    logger.error(f"[LLMRouter] Not failing over — {err.message[:300]}")
                    yield "error", err.message
                    return

                if emitted > 0:
                    # Already spoken aloud; a retry would repeat itself.
                    logger.error(
                        f"[LLMRouter] '{provider.name}' failed after {emitted} event(s) — "
                        f"cannot fail over mid-stream without duplicating output."
                    )
                    yield "error", (
                        f"Connection to {provider.name} dropped mid-response. Please try again."
                    )
                    return

                if not is_last:
                    logger.warning(
                        f"[LLMRouter] '{provider.name}' failed before output; "
                        f"failing over to '{providers[index + 1].name}'."
                    )

            except Exception as exc:  # noqa: BLE001 — a bug here must not kill the turn
                wrapped = ProviderError(f"{provider.name} unexpected error: {exc}", provider.name)
                provider.breaker.record_failure(wrapped)
                failures.append(f"{provider.name}: {exc}")
                logger.error(f"[LLMRouter] Unhandled error in '{provider.name}': {exc}", exc_info=True)
                if emitted > 0:
                    yield "error", "The response was interrupted. Please try again."
                    return

        detail = " | ".join(failures) if failures else "no provider produced a response"
        logger.error(f"[LLMRouter] Every provider failed. {detail}")
        yield "error", (
            "All AI providers are currently unavailable. "
            "Check your API keys and internet connection."
        )

    # ── diagnostics ──────────────────────────────────────────────────────────

    def _no_providers_message(self) -> str:
        if not self.providers:
            return (
                "No LLM providers configured. Set LLM_PROVIDER_CHAIN and at least one API key "
                "(e.g. GOOGLE_API_KEY) in server/.env."
            )
        missing = {p.name: p.availability_error() for p in self.providers if p.availability_error()}
        if missing:
            detail = ", ".join(f"{name} ({reason})" for name, reason in missing.items())
            return f"No LLM provider has valid credentials: {detail}"
        return "No LLM provider is currently reachable."

    def status(self) -> Dict[str, Any]:
        """Health snapshot for the /health endpoint."""
        return {
            "chain": [p.name for p in self.providers],
            "providers": {
                p.name: {
                    "model": p.model,
                    "configured": p.availability_error() is None,
                    "unavailable_reason": p.availability_error(),
                    **p.breaker.snapshot(),
                }
                for p in self.providers
            },
        }

    def reset_circuits(self) -> None:
        """Clear all cooldowns — useful right after adding a key, so you don't
        wait out a bench period caused by the missing one."""
        for provider in self.providers:
            provider.breaker.record_success()
        logger.info("[LLMRouter] All circuit breakers reset.")


# Module-level singleton, mirroring the old `gemini_client` usage.
_router: Optional[LLMRouter] = None


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router


def reload_router() -> LLMRouter:
    """Rebuild from current env — call after editing keys without a restart."""
    global _router
    _router = LLMRouter()
    return _router
