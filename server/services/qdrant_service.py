import os
from typing import Optional
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

# Load model locally for fast embeddings
embedder = SentenceTransformer('all-MiniLM-L6-v2')
COLLECTION_NAME = "ceres_memory"

import asyncio

_qdrant_client: Optional[AsyncQdrantClient] = None

def get_qdrant_client() -> AsyncQdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        url = os.getenv("QDRANT_URL")
        api_key = os.getenv("QDRANT_API_KEY")
        _qdrant_client = AsyncQdrantClient(url=url, api_key=api_key)
    return _qdrant_client

async def init_qdrant():
    client = get_qdrant_client()
    exists = await client.collection_exists(collection_name=COLLECTION_NAME)
    if not exists:
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=384, distance=Distance.COSINE),
        )

async def search_memory(query: str, limit: int = 2) -> list[str]:
    client = get_qdrant_client()
    loop = asyncio.get_event_loop()
    vector = await loop.run_in_executor(
        None, lambda: embedder.encode(query).tolist()
    )
    
    results = await client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        limit=limit,
        score_threshold=0.72,
    )
    
    return [hit.payload["fact"] for hit in results.points if hit.payload]

async def store_memory(fact: str, importance: float = 1.0):
    client = get_qdrant_client()
    loop = asyncio.get_event_loop()
    vector = await loop.run_in_executor(
        None, lambda: embedder.encode(fact).tolist()
    )
    
    import uuid
    point_id = str(uuid.uuid4())
    
    await client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            PointStruct(
                id=point_id,
                vector=vector,
                payload={"fact": fact, "importance": importance}
            )
        ]
    )
    
    try:
        from server.core.context_manager import clear_memory_cache
        clear_memory_cache()
    except Exception:
        pass
