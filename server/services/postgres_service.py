import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, String, DateTime, Float, Text
from datetime import datetime
import uuid

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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
