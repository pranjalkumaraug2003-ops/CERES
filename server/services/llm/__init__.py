"""Provider-agnostic LLM layer with automatic failover.

Usage mirrors the old GeminiService — one object, one method:

    from server.services.llm import get_router

    router = get_router()
    async for event_type, data in router.generate_stream(contents, tools=tools):
        ...

Configure the chain in server/.env:

    LLM_PROVIDER_CHAIN=gemini,groq,openrouter
    GOOGLE_API_KEY=...
    GROQ_API_KEY=...
"""

from server.services.llm.base import (
    LLMProvider,
    ProviderAuthError,
    ProviderBadRequest,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimited,
    ProviderServerError,
    ProviderTimeout,
    ProviderUnavailable,
    close_http_client,
)
from server.services.llm.router import PROVIDER_REGISTRY, LLMRouter, get_router, reload_router

__all__ = [
    "LLMProvider",
    "LLMRouter",
    "PROVIDER_REGISTRY",
    "ProviderAuthError",
    "ProviderBadRequest",
    "ProviderConnectionError",
    "ProviderError",
    "ProviderRateLimited",
    "ProviderServerError",
    "ProviderTimeout",
    "ProviderUnavailable",
    "close_http_client",
    "get_router",
    "reload_router",
]
