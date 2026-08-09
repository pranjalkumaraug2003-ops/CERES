import os
import json
import logging
import httpx
from server.services.qdrant_service import store_memory
from server.services.postgres_service import log_episodic_memory

logger = logging.getLogger(__name__)

MEMORY_EXTRACTOR_SYSTEM = """You are the Memory Extraction Agent.
Analyze the conversation and extract any NEW, PERSISTENT facts about the user.
Exclude ephemeral information (like a one-off request or error).

Respond ONLY with a JSON array of objects:
[
  {
    "fact": "User prefers dark mode",
    "importance": 0.8
  }
]
If nothing new/important was learned, return [].
"""

async def run_memory_extraction(thread_id: str, query: str, final_response: str) -> None:
    """Analyzes the exchange post-response to pull out user facts and record them to database stores."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("[MemoryService] GOOGLE_API_KEY is not configured.")
        return

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"User Query: {query}\nCeres Response: {final_response}"}
                ]
            }
        ],
        "systemInstruction": {
            "parts": [{"text": MEMORY_EXTRACTOR_SYSTEM}]
        },
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.0
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.error(f"[MemoryService] Gemini extraction request failed: {response.text}")
                return
                
            res_json = response.json()
            parts = res_json.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            if not parts or "text" not in parts[0]:
                return
                
            text = parts[0]["text"].strip()
            
            # Clean and parse JSON array output
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                facts = json.loads(text[start:end])
                for item in facts:
                    fact = item.get("fact")
                    if not fact:
                        continue
                    importance = item.get("importance", 0.5)
                    
                    # Store fact in both local vector memory (Qdrant) and relational logs
                    await store_memory(fact, importance)
                    await log_episodic_memory(fact, thread_id, importance)
                    logger.info(f"[MemoryService] Extracted and stored user fact: '{fact}' (Importance: {importance})")
    except Exception as e:
        logger.error(f"[MemoryService] Error running background memory extraction: {e}", exc_info=True)
