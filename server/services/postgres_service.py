import os
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, DateTime, Float, Text
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

# Build the engine only when a URL exists. Previously this ran unconditionally,
# so an unset DATABASE_URL raised at *import* time — and because
# server/tools/__init__.py imports every tool module (which chains here through
# reminder_service), the entire app became unimportable without Postgres.
# Now the failure is deferred to actual use, matching how redis_service
# degrades, so CERES boots and simply loses command history / episodic memory.
if DATABASE_URL:
    engine = create_async_engine(DATABASE_URL, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
else:
    logger.warning(
        "[PostgresService] DATABASE_URL not configured. Command history, episodic "
        "memory, reminders, and the user profile store are disabled."
    )
    engine = None

    def AsyncSessionLocal(*args, **kwargs):  # type: ignore[misc]
        raise RuntimeError(
            "DATABASE_URL is not configured — set it in server/.env to enable "
            "Postgres-backed features."
        )

Base = declarative_base()

class EpisodicMemory(Base):
    __tablename__ = "episodic_memory"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, default=datetime.utcnow)
    fact = Column(String, nullable=False)
    importance_score = Column(Float, default=1.0)
    source_thread_id = Column(String, nullable=True)

class UserProfileRecord(Base):
    __tablename__ = "user_profiles"
    id = Column(String, primary_key=True, default="default")
    data = Column(Text, nullable=False)  # JSON blob

async def init_postgres():
    if engine is None:
        logger.warning("[PostgresService] Skipping schema init — DATABASE_URL not set.")
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def log_episodic_memory(fact: str, thread_id: str, importance: float = 1.0):
    async with AsyncSessionLocal() as session:
        memory = EpisodicMemory(
            fact=fact,
            importance_score=importance,
            source_thread_id=thread_id
        )
        session.add(memory)
        await session.commit()
