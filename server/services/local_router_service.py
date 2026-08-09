import re
import asyncio
import logging
from functools import lru_cache
from typing import Optional, Tuple, Dict, Any
import numpy as np

logger = logging.getLogger(__name__)

# Try to reuse the loaded SentenceTransformer model from qdrant_service to save RAM
try:
    from server.services.qdrant_service import embedder as model
except ImportError:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("all-MiniLM-L6-v2")

# All 8 supported intents mapped to search terms
ROUTES = {
    "weather":  "weather forecast temperature rain condition forecast today outside temperature degrees cloud wind snow",
    "music":    "spotify songs music playback playlist volume control next track play pause mute stop song album artist",
    "maps":     "maps navigation directions traffic route search web browse open url website youtube locate find nearest search online web page how to get to",
    "calendar": "calendar schedule meeting reminder event task appointment due calendar events upcoming plan add agenda list",
    "code":     "code programming debug error script command line shell execution terminal powershell cmd command run python script test execution",
    "gmail":    "gmail email mail inbox unread messages send email message write contact compose draft letter to inbox",
    "finance":  "exchange rate gold price crypto price bitcoin currency rate convert stock price conversion dollar rupee euro rate price of precious metals forex conversion",
    "system":   "system stats cpu load ram disk battery screenshot screen capture lock pc close application terminate open app launch notepad chrome calculator delete file remove system resource",
}

# Precompute and normalize route phrase embeddings at startup
ROUTE_EMBEDDINGS: Dict[str, np.ndarray] = {}
for name, phrase in ROUTES.items():
    try:
        vec = model.encode(phrase)
        norm = np.linalg.norm(vec)
        ROUTE_EMBEDDINGS[name] = vec / norm if norm > 0 else vec
        logger.info(f"[LocalRouter] Precomputed embedding for route: {name}")
    except Exception as e:
        logger.error(f"[LocalRouter] Failed to precompute embedding for route {name}: {e}")

# Normalized embedding function with LRU cache. Must return L2-normalized vector.
@lru_cache(maxsize=512)
def embed_query_sync(query: str) -> np.ndarray:
    vec = model.encode(query)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec

# Reflex patterns to catch common commands instantly without embedding inference
REFLEX_PATTERNS = {
    "greeting": re.compile(r"^(hi|hello|hey|good morning|sup)\b", re.I),
    "stop":     re.compile(r"\b(stop|cancel|pause|shut up)\b", re.I),
    "time":     re.compile(r"what(\'s| is) the time|current time", re.I),
    "thanks":   re.compile(r"^(thanks|thank you|cheers|ty)\b", re.I),
}

MEDIA_REFLEX_PATTERNS = {
    "volume_up": re.compile(r"\b(volume up|increase volume|turn volume up|turn it up|make it louder)\b", re.I),
    "volume_down": re.compile(r"\b(volume down|decrease volume|turn volume down|turn it down|make it quieter)\b", re.I),
    "mute": re.compile(r"\b(mute|unmute|silence volume)\b", re.I),
    "play_pause": re.compile(r"\b(play music|pause music|resume music|play track|pause track|resume track|play song|pause song|resume song|pause playback|resume playback|stop music)\b", re.I),
    "next": re.compile(r"\b(next song|skip song|next track|skip track|skip)\b", re.I),
    "prev": re.compile(r"\b(previous song|prev song|previous track|prev track|go back)\b", re.I),
}

from typing import Union

def check_reflex(query: str) -> Optional[Union[str, dict]]:
    """Instant regex matching layer. Returns a string for simple reflexes, or a dictionary for tool calls."""
    clean_query = query.lower().strip()
    
    # 1. Check media control reflexes
    for action, pattern in MEDIA_REFLEX_PATTERNS.items():
        if pattern.search(clean_query):
            return {
                "type": "tool",
                "tool_name": "media_control",
                "args": {"action": action}
            }
            
    # 2. Check simple text responses
    for intent, pattern in REFLEX_PATTERNS.items():
        if pattern.search(clean_query):
            return intent
    return None

async def route_intent(query: str) -> Tuple[str, float]:
    """Computes similarity of query against routes in a non-blocking thread executor."""
    loop = asyncio.get_event_loop()
    try:
        q_vec = await loop.run_in_executor(
            None, embed_query_sync, query.lower().strip()
        )
        
        # Calculate dot product as cosine similarity (since vectors are pre-normalized)
        scores = {
            name: float(np.dot(q_vec, r_vec))
            for name, r_vec in ROUTE_EMBEDDINGS.items()
        }
        
        if not scores:
            return "general", 0.0
            
        best = max(scores, key=scores.get)
        # Cosine score threshold of 0.20 for optimal mapping coverage
        if scores[best] > 0.20:
            return best, scores[best]
        return "general", scores[best]
    except Exception as e:
        logger.error(f"[LocalRouter] Error during query routing: {e}", exc_info=True)
        return "general", 0.0

async def classify_intent(query: str) -> Optional[dict]:
    """Standardized entrypoint. Checks reflexes, Redis cache, and similarity router.
    Returns: {"intent": str, "confidence": float, "key_params": dict}
    """
    # 1. Reflex layer check
    reflex = check_reflex(query)
    if reflex:
        logger.debug(f"[LocalRouter] Reflex match: {reflex}")
        return {
            "intent": reflex,
            "confidence": 1.0,
            "key_params": {}
        }
        
    # 2. Redis intent cache check
    from server.services.redis_service import get_cached_intent, cache_intent
    try:
        cached = await get_cached_intent(query)
        if cached:
            logger.debug(f"[LocalRouter] Intent cache hit for '{query}': {cached}")
            return {
                "intent": cached["intent"],
                "confidence": cached["confidence"],
                "key_params": {}
            }
    except Exception as e:
        logger.warning(f"[LocalRouter] Cache read failed: {e}")

    # 3. Embedding cosine similarity router
    intent, confidence = await route_intent(query)
    logger.debug(f"[LocalRouter] Similarity match: intent={intent}, score={confidence:.3f}")
    
    # 4. Save to Redis cache
    try:
        await cache_intent(query, intent, confidence)
    except Exception as e:
        logger.warning(f"[LocalRouter] Cache write failed: {e}")
        
    return {
        "intent": intent,
        "confidence": confidence,
        "key_params": {}
    }
