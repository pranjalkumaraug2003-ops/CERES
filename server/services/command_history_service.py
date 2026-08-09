"""
command_history_service.py — Tracks all CERES interactions for analytics.
Stores in Postgres: input, response, agent used, timestamp.
"""
import json
from datetime import datetime

async def log_command(thread_id: str, input_query: str, final_response: str, active_agent: str, router_source: str = "gemini", latency_ms: float = 0.0):
    """Log a completed conversation turn."""
    try:
        from server.services.postgres_service import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            await session.execute(text("""
                INSERT INTO command_history (thread_id, query, response, agent, timestamp, router_source, latency_ms)
                VALUES (:tid, :q, :r, :a, :ts, :rs, :lat)
            """), {
                "tid": thread_id,
                "q": input_query[:1000],
                "r": final_response[:2000],
                "a": active_agent,
                "ts": datetime.utcnow().isoformat(),
                "rs": router_source,
                "lat": latency_ms
            })
            await session.commit()
    except Exception as e:
        print(f"[History] Log error: {e}")

async def get_recent_history(limit: int = 20) -> list[dict]:
    """Fetch recent command history."""
    try:
        from server.services.postgres_service import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("""
                SELECT query, response, agent, timestamp
                FROM command_history
                ORDER BY timestamp DESC
                LIMIT :limit
            """), {"limit": limit})
            rows = result.fetchall()
            return [
                {"query": r[0], "response": r[1], "agent": r[2], "timestamp": r[3]}
                for r in rows
            ]
    except Exception as e:
        print(f"[History] Fetch error: {e}")
        return []

async def init_history_table():
    """Create the command_history table if it doesn't exist."""
    try:
        from server.services.postgres_service import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            await session.execute(text("""
                CREATE TABLE IF NOT EXISTS command_history (
                    id SERIAL PRIMARY KEY,
                    thread_id VARCHAR(64),
                    query TEXT,
                    response TEXT,
                    agent VARCHAR(64),
                    timestamp VARCHAR(32),
                    router_source VARCHAR(32),
                    latency_ms REAL
                )
            """))
            # Safely add columns if the table already existed from before Phase 4
            await session.execute(text("ALTER TABLE command_history ADD COLUMN IF NOT EXISTS router_source VARCHAR(32);"))
            await session.execute(text("ALTER TABLE command_history ADD COLUMN IF NOT EXISTS latency_ms REAL;"))
            await session.commit()
    except Exception as e:
        print(f"[History] Table init error: {e}")
