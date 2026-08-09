import os
import json
import logging
from typing import List, Dict, Any, Optional
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_redis_client: Optional[aioredis.Redis] = None
_redis_available = True

# In-memory fallbacks for offline mode or connection errors
_memory_session_cache: Dict[str, List[Dict[str, str]]] = {}
_memory_intent_cache: Dict[str, Dict[str, Any]] = {}

def get_redis_client() -> Optional[aioredis.Redis]:
    global _redis_client, _redis_available
    if not _redis_available:
        return None
        
    if _redis_client is None:
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            logger.warning("[RedisService] REDIS_URL not configured. Running in offline/memory fallback mode.")
            _redis_available = False
            return None
            
        try:
            # Create persistent connection pool
            _redis_client = aioredis.from_url(
                redis_url, 
                encoding="utf-8", 
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0
            )
            logger.info("[RedisService] Connected to Redis successfully.")
        except Exception as e:
            logger.error(f"[RedisService] Failed to initialize Redis connection: {e}")
            _redis_available = False
            return None
            
    return _redis_client

async def close_redis_client() -> None:
    """Closes the Redis client connection pool."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
            logger.info("[RedisService] Redis connection closed.")
        except Exception as e:
            logger.error(f"[RedisService] Error closing Redis client: {e}")
        finally:
            _redis_client = None

async def get_session_history(thread_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Retrieve last N turns for the conversation thread."""
    client = get_redis_client()
    key = f"ceres:session:{thread_id}"
    
    if not client:
        history = _memory_session_cache.get(thread_id, [])
        return history[-limit:]
        
    try:
        data = await client.get(key)
        if data:
            history = json.loads(data)
            return history[-limit:]
    except Exception as e:
        logger.warning(f"[RedisService] Error reading session history from Redis: {e}. Falling back to memory.")
        history = _memory_session_cache.get(thread_id, [])
        return history[-limit:]
        
    return []

async def add_session_turn(thread_id: str, query: str, response: str) -> None:
    """Append a new conversation turn to the thread's session history."""
    client = get_redis_client()
    key = f"ceres:session:{thread_id}"
    
    # Update local memory fallback first
    if thread_id not in _memory_session_cache:
        _memory_session_cache[thread_id] = []
    _memory_session_cache[thread_id].append({"role": "user", "text": query})
    _memory_session_cache[thread_id].append({"role": "model", "text": response})
    # Keep local memory bounded
    if len(_memory_session_cache[thread_id]) > 20:
        _memory_session_cache[thread_id] = _memory_session_cache[thread_id][-20:]
        
    if not client:
        return
        
    try:
        data = await client.get(key)
        history = json.loads(data) if data else []
        history.append({"role": "user", "text": query})
        history.append({"role": "model", "text": response})
        
        # Limit history to prevent excessive context size
        if len(history) > 20:
            history = history[-20:]
            
        await client.set(key, json.dumps(history), ex=3600)  # 1 hour TTL
    except Exception as e:
        logger.warning(f"[RedisService] Error saving session history to Redis: {e}")

async def cache_intent(query: str, intent: str, confidence: float) -> None:
    """Cache the classified intent of a query."""
    client = get_redis_client()
    clean_query = query.lower().strip()
    key = f"ceres:intent:{clean_query}"
    val = {"intent": intent, "confidence": confidence}
    
    _memory_intent_cache[clean_query] = val
    
    if not client:
        return
        
    try:
        await client.set(key, json.dumps(val), ex=300)  # 5 minutes TTL
    except Exception as e:
        logger.warning(f"[RedisService] Error saving intent to Redis cache: {e}")

async def get_cached_intent(query: str) -> Optional[Dict[str, Any]]:
    """Retrieve the cached intent of a query if exists."""
    client = get_redis_client()
    clean_query = query.lower().strip()
    key = f"ceres:intent:{clean_query}"
    
    if not client:
        return _memory_intent_cache.get(clean_query)
        
    try:
        data = await client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning(f"[RedisService] Error reading intent from Redis cache: {e}. Falling back to memory.")
        return _memory_intent_cache.get(clean_query)
        
    return None
