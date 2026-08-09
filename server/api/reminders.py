from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from server.services.reminder_service import create_reminder, get_active_reminders, mark_reminder_completed

router = APIRouter()

class ReminderCreate(BaseModel):
    title: str
    due_datetime: datetime
    recurrence: Optional[str] = None

@router.get("/")
async def list_reminders():
    reminders = await get_active_reminders()
    return [{"id": r.id, "title": r.title, "due": r.due_datetime.isoformat()} for r in reminders]

@router.post("/")
async def add_reminder(req: ReminderCreate):
    r = await create_reminder(req.title, req.due_datetime, req.recurrence)
    return {"id": r.id, "status": "created"}

@router.delete("/{reminder_id}")
async def complete_reminder(reminder_id: str):
    await mark_reminder_completed(reminder_id)
    return {"status": "completed"}
