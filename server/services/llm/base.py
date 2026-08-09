"""Provider interface, error taxonomy, and circuit breaker for the LLM router.

Every provider normalizes to ONE streaming contract — the same one
GeminiService already used, so callers never learn which backend served them:

    ("token",         str)              incremental text
    ("function_call", (name, args))     tool invocation
    ("error",         str)              terminal failure

Providers raise ProviderError subclasses instead of yielding ("error", ...) so
the router can classify the failure and decide whether to fail over.
"""

import os
import time
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

# One connection pool shared by every HTTP-based provider. Keep-alive across
# providers means a failover doesn't pay a fresh TLS handshake.
_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(120.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


# ── Error taxonomy ───────────────────────────────────────────────────────────
# The distinction that matters: does trying a DIFFERENT provider help?


class ProviderError(Exception):
    """Base failure. `cooldown` is how long to bench the provider afterwards."""

    cooldown: float = 30.0
    should_failover: bool = True

    def __init__(self, message: str, provider: str = "", retry_after: Optional[float] = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.retry_after = retry_after


class ProviderRateLimited(ProviderError):
    """429. Another provider almost certainly helps."""

    cooldown = 60.0


class ProviderServerError(ProviderError):
    """5xx / overloaded. Transient on their side."""

    cooldown = 30.0


class ProviderTimeout(ProviderError):
    """Took too long. For a voice assistant this is as good as a failure."""

    cooldown = 30.0


class ProviderConnectionError(ProviderError):
    """DNS/TCP/TLS failure — or the user's internet is down."""

    cooldown = 30.0


class ProviderAuthError(ProviderError):
    """401/403. The key is wrong or unfunded; this will not fix itself.
    Bench it for a long time rather than burning a retry every request."""

    cooldown = 600.0


class ProviderBadRequest(ProviderError):
    """400. WE built a malformed payload — every other provider will reject it
    too. Failing over would just multiply the same error, so don't."""

    cooldown = 0.0
    should_failover = False


class ProviderUnavailable(ProviderError):
    """No API key, or the SDK isn't installed. Never even attempted."""

    cooldown = 0.0


def classify_http_error(status: int, body: str, provider: str) -> ProviderError:
    """Map an HTTP status onto the taxonomy above."""
    snippet = body[:400].replace("\n", " ")
    if status in (401, 403):
        return ProviderAuthError(f"{provider} auth rejected ({status}): {snippet}", provider)
    if status == 429:
        return ProviderRateLimited(f"{provider} rate limited (429): {snippet}", provider)
    if status == 400:
        return ProviderBadRequest(f"{provider} rejected the request (400): {snippet}", provider)
    if status >= 500:
        return ProviderServerError(f"{provider} server error ({status}): {snippet}", provider)
    return ProviderError(f"{provider} HTTP {status}: {snippet}", provider)


def classify_exception(exc: Exception, provider: str) -> ProviderError:
    """Map an httpx/transport exception onto the taxonomy above."""
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)):
        return ProviderTimeout(f"{provider} timed out: {exc}", provider)
    if isinstance(exc, httpx.HTTPError):
        return ProviderConnectionError(f"{provider} connection failed: {exc}", provider)
    return ProviderError(f"{provider} unexpected failure: {exc}", provider)


# ── Circuit breaker ──────────────────────────────────────────────────────────


class CircuitBreaker:
    """Keeps a failing provider benched so we stop paying its latency on every
    request. Cooldown doubles on consecutive failures, capped at MAX_COOLDOWN.
    """

    MAX_COOLDOWN = 600.0

    def __init__(self, name: str):
        self.name = name
        self.consecutive_failures = 0
        self.open_until = 0.0
        self.last_error: Optional[str] = None
        self.total_failures = 0
        self.total_successes = 0

    @property
    def is_open(self) -> bool:
        """True while the provider is benched."""
        return time.time() < self.open_until

    @property
    def seconds_remaining(self) -> float:
        return max(0.0, self.open_until - time.time())

    def record_success(self) -> None:
        if self.consecutive_failures:
            logger.info(f"[Circuit:{self.name}] Recovered after {self.consecutive_failures} failure(s).")
        self.consecutive_failures = 0
        self.open_until = 0.0
        self.last_error = None
        self.total_successes += 1

    def record_failure(self, error: ProviderError) -> None:
        self.consecutive_failures += 1
        self.total_failures += 1
        self.last_error = error.message

        base = error.retry_after if error.retry_after else error.cooldown
        cooldown = min(base * (2 ** (self.consecutive_failures - 1)), self.MAX_COOLDOWN)
        self.open_until = time.time() + cooldown
        logger.warning(
            f"[Circuit:{self.name}] OPEN for {cooldown:.0f}s "
            f"(failure #{self.consecutive_failures}): {error.message[:200]}"
        )

    def snapshot(self) -> Dict[str, Any]:
        return {
            "state": "open" if self.is_open else "closed",
            "cooldown_remaining_s": round(self.seconds_remaining, 1),
            "consecutive_failures": self.consecutive_failures,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "last_error": self.last_error,
        }


# ── Provider interface ───────────────────────────────────────────────────────


class LLMProvider(ABC):
    """One backend. Subclasses translate the canonical Gemini-shaped request
    into their own wire format and normalize the response back."""

    name: str = "unnamed"
    model: str = ""
    #: Env var holding the credential. None means no auth needed (e.g. Ollama).
    api_key_env: Optional[str] = None

    def __init__(self, model: Optional[str] = None):
        if model:
            self.model = model
        self.breaker = CircuitBreaker(self.name)

    @property
    def api_key(self) -> Optional[str]:
        return os.getenv(self.api_key_env) if self.api_key_env else None

    def availability_error(self) -> Optional[str]:
        """Why this provider can't be used at all, or None if it's usable.
        Checked once per request — cheap, and lets a key added at runtime work."""
        if self.api_key_env and not self.api_key:
            return f"{self.api_key_env} not set"
        return None

    @abstractmethod
    def stream(
        self,
        contents: List[Dict[str, Any]],
        system_instruction: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.4,
        max_output_tokens: Optional[int] = None,
    ) -> AsyncGenerator[Tuple[str, Any], None]:
        """Yield ("token", str) / ("function_call", (name, args)).

        MUST raise a ProviderError subclass on failure — never yield
        ("error", ...); the router needs the exception to classify and fail over.

        `contents` and `tools` arrive in Gemini format (the canonical shape used
        throughout CERES); translating them is the subclass's job.
        """
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.name}/{self.model}>"
