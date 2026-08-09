import asyncio
import logging
import time
from datetime import datetime
from server.services.profile_service import get_profile
from server.services.qdrant_service import is_qdrant_configured, search_memory
from server.core.security import ContextEnvelope

logger = logging.getLogger(__name__)

# Hard ceiling on the memory lookup. Long-term memory is a nice-to-have on any
# single turn; making the user wait for it is not. If Qdrant can't answer in
# this long, we proceed without memories rather than stall the reply.
MEMORY_SEARCH_TIMEOUT = 1.5

# Query-specific memory cache: clean_query -> (timestamp, memories_list)
_memory_cache = {}

def clear_memory_cache() -> None:
    """Invalidates the context memory cache. Called when new memories are stored."""
    _memory_cache.clear()
    logger.debug("[ContextManager] Memory cache cleared.")

async def build_context(query: str, request_id: str) -> ContextEnvelope:
    """Aggregates user profile, Qdrant memories, and host system state parameters
    to formulate a secure ContextEnvelope.
    
    PERFORMANCE: Memory retrieval and profile fetching run concurrently
    via asyncio.gather() instead of sequentially. This cuts context_building
    from ~1.3s to ~0.5s.
    
    All data is treated as TRUSTED context and sanitized for injection attempts.
    """
    envelope = ContextEnvelope()

    # 1. Run memory search and profile fetch CONCURRENTLY
    memories_result = None
    profile_result = None

    clean_query = query.lower().strip()

    async def _fetch_memories():
        # Nothing to search, and attempting it costs seconds in refused-
        # connection retries against the localhost default.
        if not is_qdrant_configured():
            return None

        now = time.time()
        if clean_query in _memory_cache:
            ts, cached_mem = _memory_cache[clean_query]
            if now - ts < 30.0:
                logger.debug(f"[ContextManager] Memory cache hit for: '{clean_query}'")
                return cached_mem
        try:
            mems = await asyncio.wait_for(
                search_memory(query, limit=3), timeout=MEMORY_SEARCH_TIMEOUT
            )
            _memory_cache[clean_query] = (now, mems)
            return mems
        except asyncio.TimeoutError:
            logger.warning(
                f"[ContextManager] Memory search exceeded {MEMORY_SEARCH_TIMEOUT}s; "
                f"continuing without long-term memory."
            )
            return None
        except Exception as e:
            logger.warning(f"[ContextManager] Failed to fetch Qdrant memories: {e}")
            return None

    async def _fetch_profile():
        try:
            return await get_profile()
        except Exception as e:
            logger.warning(f"[ContextManager] Failed to fetch user profile: {e}")
            return None

    memories_result, profile_result = await asyncio.gather(
        _fetch_memories(),
        _fetch_profile()
    )

    # 2. Process memories
    if memories_result:
        memory_block = "User Memory Facts:\n" + "\n".join(f"- {m}" for m in memories_result)
        envelope.add_block("qdrant_memory", memory_block, is_trusted=True)

    # 3. Process profile
    if profile_result:
        try:
            profile_dict = profile_result.to_dict() if hasattr(profile_result, "to_dict") else {}
            if profile_dict:
                contacts = profile_dict.get("contacts", [])
                contacts_str = ", ".join(
                    f"{c.get('name') or c.get('nickname')} ({c.get('relationship')})" 
                    for c in contacts[:5]
                ) or "No contacts saved."
                
                profile_block = (
                    f"User Profile Details:\n"
                    f"- Name: {profile_dict.get('name', 'User')}\n"
                    f"- Location: {profile_dict.get('location', 'Unknown')}\n"
                    f"- Timezone: {profile_dict.get('timezone', 'UTC')}\n"
                    f"- Primary Contacts: {contacts_str}"
                )
                envelope.add_block("user_profile", profile_block, is_trusted=True)
        except Exception as e:
            logger.warning(f"[ContextManager] Failed to process user profile: {e}")

    # 4. Add Host System Parameters (instant, no I/O)
    now = datetime.now()
    system_block = (
        f"Host System Metrics:\n"
        f"- Local Time: {now.strftime('%I:%M:%S %p')}\n"
        f"- Current Date: {now.strftime('%A, %B %d, %Y')}\n"
        f"- Platform: Windows 11\n"
        f"- Request ID: {request_id}"
    )
    envelope.add_block("system_state", system_block, is_trusted=True)

    return envelope
