import re
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from server.tools.tool_executor import register_tool
from server.tools.tool_result import ToolResult

# Import underlying integrations
from server.services.weather_service import get_weather as _fetch_weather
from server.services.gmail_service import send_email as _send_email, get_unread_emails as _get_unread_emails
from server.services.calendar_service import get_events_today as _get_events_today, get_events_this_week as _get_events_this_week
from server.services.reminder_service import create_reminder as _create_db_reminder

logger = logging.getLogger(__name__)

async def get_weather_tool(location: str, forecast_days: int = 1) -> ToolResult:
    """Wrapper tool to retrieve weather using the weather service.
    Supports current weather and daily forecasts up to 7 days.
    """
    res = await _fetch_weather(location, forecast_days=forecast_days)
    if "error" in res:
        return ToolResult(status="error", data=res, summary=f"Could not get weather for {location}.", error=res["error"])
    return ToolResult(status="success", data=res, summary=res.get("summary", f"Weather data for {res.get('location', location)}."))

async def send_email_tool(to: str, subject: str, body: str) -> ToolResult:
    """[DANGEROUS] Sends an email via Gmail API wrapper. Requires user confirmation."""
    try:
        success = await _send_email(to, subject, body)
        if success:
            return ToolResult(
                status="success",
                data={"to": to, "subject": subject},
                summary=f"Successfully sent email to {to} with subject: '{subject}'."
            )
        return ToolResult(status="error", data={}, summary="Gmail API failed to send email.")
    except Exception as e:
        err_msg = f"Gmail send failed: {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(status="error", data={}, summary="Failed to send email.", error=err_msg)

async def get_unread_emails_tool(max_results: int = 10) -> ToolResult:
    """Fetches unread emails from the inbox."""
    try:
        emails = await _get_unread_emails(max_results=max_results)
        data = [
            {
                "sender": e.sender,
                "sender_email": e.sender_email,
                "subject": e.subject,
                "preview": e.preview,
                "timestamp": e.timestamp,
                "thread_id": e.thread_id
            }
            for e in emails
        ]
        
        if not data:
            summary = "You have no unread emails in your inbox."
        elif len(data) == 1:
            summary = f"You have 1 unread email from {data[0]['sender']}: '{data[0]['subject']}'."
        else:
            summary = f"You have {len(data)} unread emails. The latest is from {data[0]['sender']}: '{data[0]['subject']}'."
            
        return ToolResult(status="success", data={"emails": data}, summary=summary)
    except Exception as e:
        err_msg = f"Gmail retrieval failed: {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(status="error", data={}, summary="Could not check unread emails.", error=err_msg)

async def get_calendar_events_tool(duration: str) -> ToolResult:
    """Queries calendar events for today or this week."""
    dur = duration.lower().strip()
    try:
        if dur == "today":
            events = await _get_events_today()
        else:
            events = await _get_events_this_week()
            
        data = [
            {
                "title": ev.title,
                "start_time": ev.start_time,
                "end_time": ev.end_time,
                "date": ev.date,
                "attendees": ev.attendees,
                "location": ev.location,
                "is_all_day": ev.is_all_day
            }
            for ev in events
        ]
        
        if not data:
            summary = f"You have no events scheduled for {dur}."
        elif len(data) == 1:
            summary = f"You have 1 event scheduled: '{data[0]['title']}' at {data[0]['start_time']}."
        else:
            summary = f"You have {len(data)} events scheduled. First is '{data[0]['title']}' at {data[0]['start_time']}."
            
        return ToolResult(status="success", data={"events": data}, summary=summary)
    except Exception as e:
        err_msg = f"Calendar retrieval failed: {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(status="error", data={}, summary="Could not retrieve calendar events.", error=err_msg)

def _parse_due_time(time_str: str) -> datetime:
    """Helper to parse relative time phrases (e.g. 'in 10 minutes', 'tomorrow') into datetime."""
    now = datetime.utcnow()
    t = time_str.lower().strip()
    
    # Check 'in X minutes'
    m = re.search(r"in\s+(\d+)\s+min", t)
    if m:
        return now + timedelta(minutes=int(m.group(1)))
        
    # Check 'in X hours'
    m = re.search(r"in\s+(\d+)\s+hour", t)
    if m:
        return now + timedelta(hours=int(m.group(1)))
        
    # Check 'in X days'
    m = re.search(r"in\s+(\d+)\s+day", t)
    if m:
        return now + timedelta(days=int(m.group(1)))
        
    if "tomorrow" in t:
        return now + timedelta(days=1)
        
    # Fallback default offset (30 minutes)
    return now + timedelta(minutes=30)

async def create_reminder_tool(title: str, due_time: str) -> ToolResult:
    """Creates a calendar-based reminder in PostgreSQL database."""
    try:
        due_dt = _parse_due_time(due_time)
        reminder = await _create_db_reminder(title, due_dt)
        return ToolResult(
            status="success",
            data={
                "reminder_id": reminder.id,
                "title": reminder.title,
                "due_datetime": reminder.due_datetime.isoformat(),
                "is_completed": reminder.is_completed
            },
            summary=f"Created reminder: '{title}' due on {reminder.due_datetime.strftime('%A, %b %d at %I:%M %p UTC')}."
        )
    except Exception as e:
        err_msg = f"Database insertion failed: {e}"
        logger.error(err_msg, exc_info=True)
        return ToolResult(status="error", data={}, summary="Could not create reminder.", error=err_msg)

# Register with central executor
register_tool("get_weather", get_weather_tool)
register_tool("send_email", send_email_tool)
register_tool("get_unread_emails", get_unread_emails_tool)
register_tool("get_calendar_events", get_calendar_events_tool)
register_tool("create_reminder", create_reminder_tool)
