import time
import numpy as np
import logging
from typing import List, Optional
from server.services.qdrant_service import embedder

logger = logging.getLogger(__name__)

# TTL (Time to Live) configuration in seconds per semantic bucket
BUCKET_TTLS = {
    "weather": 600,       # 10 minutes
    "system_stats": 30,   # 30 seconds
    "time_date": 5,       # 5 seconds
    "help": 3600          # 1 hour
}

# ---------------------------------------------------------------------------
# Buckets whose queries are inherently dynamic and should NEVER be cached.
# B-4: weather / system_stats / time_date are now governed by short TTLs
# defined in BUCKET_TTLS (600s, 30s, 5s) rather than a hard block.
# This allows semantic cache HITs on repeated identical queries within
# the TTL window while still serving live data for stale entries.
# ---------------------------------------------------------------------------
UNCACHEABLE_BUCKETS: set = set()  # Reserved for truly un-cacheable future buckets


class CacheEntry:
    def __init__(self, query: str, embedding: np.ndarray, response: str, bucket: str):
        self.query = query
        self.embedding = embedding
        self.response = response
        self.bucket = bucket
        self.timestamp = time.time()


class SemanticCache:
    """Provides vector-similarity based semantic caching using the local MiniLM embedder.
    Allows CERES to bypass cloud calls and tool execution for repetitive queries.

    CRITICAL SAFETY RULES:
    1. NEVER cache error/failure/refusal responses.
    2. NEVER cache dynamic data (weather, system stats, time).
    3. Only cache successful, factual, stable responses.
    """
    def __init__(self):
        self.entries: List[CacheEntry] = []

    def get(self, query: str, threshold: float = 0.92) -> Optional[str]:
        """Checks for a semantic hit in the cache.
        Returns the cached string response if a fresh entry is matched, or None on miss.
        Threshold raised to 0.92 (from 0.88) to prevent cross-query pollution.
        """
        # Failure Domain resilience: Cache errors should never crash query execution
        try:
            if not self.entries:
                return None

            # Get embedding of the query using the lazy-loaded model shared with Qdrant
            query_emb = embedder.encode(query)
            
            best_entry: Optional[CacheEntry] = None
            best_score = -1.0

            for entry in self.entries:
                # Compute Cosine Similarity
                dot_product = np.dot(query_emb, entry.embedding)
                norm_a = np.linalg.norm(query_emb)
                norm_b = np.linalg.norm(entry.embedding)
                similarity = dot_product / (norm_a * norm_b) if (norm_a * norm_b) > 0 else 0.0
                
                if similarity > best_score:
                    best_score = similarity
                    best_entry = entry

            if best_entry and best_score >= threshold:
                ttl = BUCKET_TTLS.get(best_entry.bucket, 60)
                elapsed = time.time() - best_entry.timestamp
                
                if elapsed < ttl:
                    logger.info(
                        f"[SemanticCache] HIT: '{query}' mapped to '{best_entry.query}' "
                        f"(Similarity: {best_score:.2%}, Bucket: {best_entry.bucket}, Age: {elapsed:.1f}s)"
                    )
                    return best_entry.response
                else:
                    # Clean up expired entry
                    logger.debug(f"[SemanticCache] Expired entry removed for: '{best_entry.query}'")
                    self.entries.remove(best_entry)
        except Exception as e:
            logger.error(f"[SemanticCache] Read error: {e}", exc_info=True)
            
        return None

    def set(self, query: str, response: str, bucket: str) -> None:
        """Stores a query, its embedding, the text response, and its TTL bucket in the cache.
        
        SAFETY: Refuses to cache responses for uncacheable buckets or responses that
        look like errors/refusals/fallbacks.
        """
        try:
            # RULE 1: Never cache dynamic/uncacheable buckets
            if bucket in UNCACHEABLE_BUCKETS:
                logger.debug(f"[SemanticCache] SKIP: Bucket '{bucket}' is uncacheable.")
                return

            # RULE 2: Never cache empty or very short responses
            if not response or len(response.strip()) < 20:
                logger.debug(f"[SemanticCache] SKIP: Response too short to cache.")
                return

            # RULE 3: Never cache responses that look like errors/refusals/fallbacks
            lower_resp = response.lower()
            refusal_indicators = [
                "i can't", "i cannot", "i'm unable", "i am unable",
                "i don't have", "i do not have",
                "sorry, i", "unfortunately,",
                "not available", "unavailable",
                "could not", "couldn't",
                "failed to", "error",
                "i can only", "not supported",
                "i'm not able", "i am not able",
                "offline fallback", "check your internet",
                "no results", "no data",
            ]
            if any(indicator in lower_resp for indicator in refusal_indicators):
                logger.info(f"[SemanticCache] SKIP: Response contains refusal/error indicator. Not caching.")
                return

            query_emb = embedder.encode(query)
            
            # Remove any identical query to avoid duplicates
            self.entries = [e for e in self.entries if e.query.lower() != query.lower()]
            
            new_entry = CacheEntry(query, query_emb, response, bucket)
            self.entries.append(new_entry)
            logger.info(f"[SemanticCache] Cached query under '{bucket}' bucket (TTL: {BUCKET_TTLS.get(bucket, 60)}s)")
        except Exception as e:
            logger.error(f"[SemanticCache] Write error: {e}", exc_info=True)

    def invalidate_bucket(self, bucket: str) -> int:
        """Removes all cache entries for a specific bucket. Returns count of entries removed."""
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.bucket != bucket]
        removed = before - len(self.entries)
        if removed:
            logger.info(f"[SemanticCache] Invalidated {removed} entries from bucket '{bucket}'.")
        return removed

    def clear(self) -> None:
        """Removes all cache entries."""
        count = len(self.entries)
        self.entries.clear()
        logger.info(f"[SemanticCache] Cleared all {count} entries.")


# Global singleton cache
semantic_cache = SemanticCache()
