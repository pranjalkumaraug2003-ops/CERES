"""Model selection facade.

Two distinct paths live here:

1. `get_router()` — the multi-provider streaming router with automatic failover.
   This is what the query pipeline uses. See `server/services/llm/`.

2. `get_flash()` / `get_pro()` — LangChain chat models, still used by
   `monitor_service.py` for background (non-streaming, non-voice) reasoning.
   These are Gemini-only with no failover; the background monitor is
   best-effort, so a transient outage there just skips one cycle.
"""

import logging
import os
from typing import Optional

from server.services.llm import LLMRouter, get_router, reload_router

logger = logging.getLogger(__name__)

FLASH = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
PRO = os.getenv("GEMINI_PRO_MODEL", "gemini-2.5-pro")

__all__ = ["get_router", "reload_router", "get_flash", "get_pro", "LLMRouter", "FLASH", "PRO"]


def get_flash(temperature: float = 0):
    """LangChain Gemini Flash — background agents (memory, automation, monitor).

    Raises ImportError if langchain-google-genai isn't installed. Callers should
    treat a failure here as "skip this background cycle", not a fatal error.
    """
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=FLASH, temperature=temperature)


def get_pro(temperature: float = 0):
    """LangChain Gemini Pro — reserved for the orchestrator / communication agent."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=PRO, temperature=temperature)
