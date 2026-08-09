import uuid
import asyncio
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.future import select
from server.services.postgres_service import Base, AsyncSessionLocal, engine

class Reminder(Base):
    __tablename__ = "reminders"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False)
    due_datetime = Column(DateTime, nullable=False)
    is_completed = Column(Boolean, default=False)
    recurrence = Column(String, nullable=True)

async def create_reminder(title: str, due: datetime, recurrence: str = None) -> Reminder:
    async with AsyncSessionLocal() as session:
        r = Reminder(title=title, due_datetime=due, recurrence=recurrence)
        session.add(r)
        await session.commit()
        await session.refresh(r)
        return r

async def get_active_reminders():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Reminder).where(Reminder.is_completed == False).order_by(Reminder.due_datetime.asc())
        )
        return result.scalars().all()

async def mark_reminder_completed(reminder_id: str):
    async with AsyncSessionLocal() as session:
        r = await session.get(Reminder, reminder_id)
        if r:
            r.is_completed = True
            await session.commit()

async def check_due_reminders(emit_func):
    while True:
        try:
            now = datetime.utcnow()
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(Reminder)
                    .where(Reminder.is_completed == False)
                    .where(Reminder.due_datetime <= now)
                )
                due = result.scalars().all()
                for r in due:
                    r.is_completed = True
                    msg = f"Reminder: {r.title}"
                    await emit_func("proactive_alert", "System Agent", msg, {"title": r.title})
                    
                    from server.services.voice_service import synthesize_speech
                    import base64
                    try:
                        audio_data, _ = await synthesize_speech(msg)
                        audio_base64 = base64.b64encode(audio_data).decode('utf-8')
                        await emit_func("tts_audio", "System Agent", "", {"audio_base64": audio_base64})
                    except Exception as e:
                        print(f"TTS Error in reminder: {e}")
                
                if due:
                    await session.commit()
        except Exception as e:
            print(f"Reminder loop error: {e}")
        await asyncio.sleep(60)
