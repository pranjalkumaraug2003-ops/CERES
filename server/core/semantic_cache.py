import json
import logging
import os
import tempfile
import time
from typing import Dict, List, Optional

import numpy as np

from server.services.qdrant_service import embedder

logger = logging.getLogger(__name__)

CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "semantic_cache.json")

# Similarity required to call two queries "the same". Too high and paraphrases
# miss (wasting an API call); too low and unrelated queries collide. Tunable
# because the right value depends on how varied your phrasing is.
DEFAULT_THRESHOLD = float(os.getenv("SEMANTIC_CACHE_THRESHOLD", "0.90"))

# Cap entries so a long-running session can't grow the cache without bound.
MAX_ENTRIES = int(os.getenv("SEMANTIC_CACHE_MAX_ENTRIES", "500"))

# Don't rewrite the file on every single query.
_SAVE_INTERVAL_SECONDS = 10.0

# ---------------------------------------------------------------------------
# TTL per semantic bucket, in seconds. The value reflects how fast the
# underlying truth changes — NOT how expensive the call was.
# ---------------------------------------------------------------------------
BUCKET_TTLS = {
    "action": 0,          # side-effecting: never cached (see ACTION_BUCKET below)
    "time_date": 5,       # the clock moves
    "system_stats": 30,   # CPU/RAM/battery move constantly
    "finance": 120,       # crypto / forex / metals move fast
    "inbox": 120,         # unread mail and calendar change under you
    "weather": 600,
    "search": 900,
    "help": 3600,         # stable conversational answers
}

#: Bucket meaning "this had a side effect — replaying the words would be a lie".
ACTION_BUCKET = "action"

# ---------------------------------------------------------------------------
# Which bucket each tool's narration belongs to.
#
# CRITICAL: every tool that *changes something* maps to ACTION_BUCKET and is
# therefore never cached. The cache is consulted BEFORE tool execution, so a
# cached "Opening Notepad now." would be replayed without opening anything —
# CERES would confidently narrate an action it never performed. Previously all
# of these fell through to the "help" bucket and were cached for an hour.
#
# Any tool absent from this map falls back to "help" (1 hour). When you add a
# new tool, decide deliberately: does it have a side effect, or is its answer
# volatile? If either, add it here.
# ---------------------------------------------------------------------------
TOOL_BUCKETS = {
    # Read-only but volatile
    "get_weather": "weather",
    "get_system_stats": "system_stats",
    "get_crypto_price": "finance",
    "get_exchange_rate": "finance",
    "get_gold_price": "finance",
    "get_unread_emails": "inbox",
    "get_calendar_events": "inbox",
    "search_web": "search",
    # Side-effecting — never cache
    "send_email": ACTION_BUCKET,
    "create_reminder": ACTION_BUCKET,
    "delete_file": ACTION_BUCKET,
    "run_shell_command": ACTION_BUCKET,
    "take_screenshot": ACTION_BUCKET,
    "lock_pc": ACTION_BUCKET,
    "open_app": ACTION_BUCKET,
    "close_application": ACTION_BUCKET,
    "open_url": ACTION_BUCKET,
    "play_youtube": ACTION_BUCKET,
    "open_maps": ACTION_BUCKET,
    "media_control": ACTION_BUCKET,
}


def bucket_for_tool(tool_name: str) -> str:
    """Bucket a tool's narration belongs in. Unknown tools get 'help'."""
    return TOOL_BUCKETS.get(tool_name, "help")


class CacheEntry:
    __slots__ = ("query", "embedding", "response", "bucket", "timestamp")

    def __init__(self, query: str, embedding: np.ndarray, response: str, bucket: str,
                 timestamp: Optional[float] = None):
        self.query = query
        self.embedding = embedding
        self.response = response
        self.bucket = bucket
        self.timestamp = timestamp if timestamp is not None else time.time()

    def to_dict(self) -> Dict:
        return {
            "query": self.query,
            "embedding": np.asarray(self.embedding, dtype=np.float32).tolist(),
            "response": self.response,
            "bucket": self.bucket,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, raw: Dict) -> "CacheEntry":
        return cls(
            query=raw["query"],
            embedding=np.asarray(raw["embedding"], dtype=np.float32),
            response=raw["response"],
            bucket=raw.get("bucket", "help"),
            timestamp=float(raw.get("timestamp", 0.0)),
        )


class SemanticCache:
    """Vector-similarity cache that lets CERES answer repeat questions without
    an API call. Persisted to disk, because the previous in-process-only version
    was wiped by every server restart — which during development meant it was
    almost always empty and saved nothing.

    SAFETY RULES:
      1. Never cache error / failure / refusal responses.
      2. Never cache anything with a side effect (ACTION_BUCKET, TTL 0).
      3. Short-lived truths get short TTLs (see BUCKET_TTLS).
    """

    def __init__(self, persist: bool = True):
        self.entries: List[CacheEntry] = []
        self.persist = persist
        self._last_saved = 0.0
        self._dirty = False
        self.hits = 0
        self.misses = 0
        if persist:
            self._load()

    # ── persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        path = os.path.abspath(CACHE_PATH)
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            now = time.time()
            loaded, expired = 0, 0
            for item in raw.get("entries", []):
                try:
                    entry = CacheEntry.from_dict(item)
                except (KeyError, TypeError, ValueError):
                    continue
                ttl = BUCKET_TTLS.get(entry.bucket, 60)
                # Drop anything that expired while we were shut down, and never
                # trust a persisted action-bucket entry (shouldn't exist).
                if ttl <= 0 or (now - entry.timestamp) >= ttl:
                    expired += 1
                    continue
                self.entries.append(entry)
                loaded += 1
            logger.info(
                f"[SemanticCache] Loaded {loaded} live entr{'y' if loaded == 1 else 'ies'} "
                f"from disk ({expired} expired while offline)."
            )
        except Exception as e:
            logger.error(f"[SemanticCache] Could not load cache from {path}: {e}")

    def save(self, force: bool = False) -> None:
        """Write the cache to disk atomically. Throttled unless `force`."""
        if not self.persist or not self._dirty:
            return
        if not force and (time.time() - self._last_saved) < _SAVE_INTERVAL_SECONDS:
            return

        path = os.path.abspath(CACHE_PATH)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = {"version": 1, "entries": [e.to_dict() for e in self.entries]}
            # temp-file + replace so a crash mid-write can't corrupt the cache
            directory = os.path.dirname(path)
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
            ) as tmp:
                json.dump(payload, tmp)
                tmp_path = tmp.name
            os.replace(tmp_path, path)
            self._last_saved = time.time()
            self._dirty = False
            logger.debug(f"[SemanticCache] Persisted {len(self.entries)} entries.")
        except Exception as e:
            logger.error(f"[SemanticCache] Could not save cache to {path}: {e}")

    # ── read / write ─────────────────────────────────────────────────────────

    def get(self, query: str, threshold: Optional[float] = None) -> Optional[str]:
        """Return a cached response for a semantically equivalent query, or None."""
        threshold = DEFAULT_THRESHOLD if threshold is None else threshold
        try:
            if not self.entries:
                self.misses += 1
                return None

            query_emb = np.asarray(embedder.encode(query), dtype=np.float32)
            query_norm = float(np.linalg.norm(query_emb))
            if query_norm == 0.0:
                self.misses += 1
                return None

            best_entry: Optional[CacheEntry] = None
            best_score = -1.0
            for entry in self.entries:
                entry_norm = float(np.linalg.norm(entry.embedding))
                if entry_norm == 0.0:
                    continue
                similarity = float(np.dot(query_emb, entry.embedding)) / (query_norm * entry_norm)
                if similarity > best_score:
                    best_score = similarity
                    best_entry = entry

            if best_entry is not None and best_score >= threshold:
                ttl = BUCKET_TTLS.get(best_entry.bucket, 60)
                elapsed = time.time() - best_entry.timestamp
                if ttl > 0 and elapsed < ttl:
                    self.hits += 1
                    logger.info(
                        f"[SemanticCache] HIT: '{query}' matched '{best_entry.query}' "
                        f"({best_score:.1%}, bucket={best_entry.bucket}, age={elapsed:.0f}s)"
                    )
                    return best_entry.response
                logger.debug(f"[SemanticCache] Expired entry dropped: '{best_entry.query}'")
                self.entries.remove(best_entry)
                self._dirty = True
        except Exception as e:
            # A cache failure must never break query execution.
            logger.error(f"[SemanticCache] Read error: {e}", exc_info=True)

        self.misses += 1
        return None

    def set(self, query: str, response: str, bucket: str) -> None:
        """Store a response, unless a safety rule forbids it."""
        try:
            ttl = BUCKET_TTLS.get(bucket, 60)

            # RULE 1: never cache a side effect. Replaying the narration would
            # claim an action happened when it did not.
            if bucket == ACTION_BUCKET or ttl <= 0:
                logger.debug(f"[SemanticCache] SKIP: bucket '{bucket}' is never cached.")
                return

            # RULE 2: too short to be a real answer
            if not response or len(response.strip()) < 20:
                logger.debug("[SemanticCache] SKIP: response too short.")
                return

            # RULE 3: never cache an error / refusal / fallback
            lowered = response.lower()
            refusal_indicators = (
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
                "please try again",
            )
            if any(indicator in lowered for indicator in refusal_indicators):
                logger.info("[SemanticCache] SKIP: response looks like an error/refusal.")
                return

            embedding = np.asarray(embedder.encode(query), dtype=np.float32)

            # Replace any identical query rather than accumulating duplicates.
            self.entries = [e for e in self.entries if e.query.lower() != query.lower()]
            self.entries.append(CacheEntry(query, embedding, response, bucket))

            # Evict oldest first if we're over the cap.
            if len(self.entries) > MAX_ENTRIES:
                self.entries.sort(key=lambda e: e.timestamp)
                dropped = len(self.entries) - MAX_ENTRIES
                self.entries = self.entries[dropped:]
                logger.debug(f"[SemanticCache] Evicted {dropped} oldest entr(y/ies).")

            self._dirty = True
            logger.info(f"[SemanticCache] Cached under '{bucket}' (TTL {ttl}s).")
            self.save()
        except Exception as e:
            logger.error(f"[SemanticCache] Write error: {e}", exc_info=True)

    # ── maintenance ──────────────────────────────────────────────────────────

    def purge_expired(self) -> int:
        now = time.time()
        before = len(self.entries)
        self.entries = [
            e for e in self.entries
            if BUCKET_TTLS.get(e.bucket, 60) > 0
            and (now - e.timestamp) < BUCKET_TTLS.get(e.bucket, 60)
        ]
        removed = before - len(self.entries)
        if removed:
            self._dirty = True
        return removed

    def invalidate_bucket(self, bucket: str) -> int:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.bucket != bucket]
        removed = before - len(self.entries)
        if removed:
            self._dirty = True
            logger.info(f"[SemanticCache] Invalidated {removed} entries from '{bucket}'.")
        return removed

    def clear(self) -> None:
        count = len(self.entries)
        self.entries.clear()
        self._dirty = True
        self.save(force=True)
        logger.info(f"[SemanticCache] Cleared all {count} entries.")

    def stats(self) -> Dict:
        total = self.hits + self.misses
        by_bucket: Dict[str, int] = {}
        for entry in self.entries:
            by_bucket[entry.bucket] = by_bucket.get(entry.bucket, 0) + 1
        return {
            "entries": len(self.entries),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
            "threshold": DEFAULT_THRESHOLD,
            "by_bucket": by_bucket,
            "persisted_to": os.path.abspath(CACHE_PATH) if self.persist else None,
        }


# Global singleton cache
semantic_cache = SemanticCache()
