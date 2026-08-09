"""
calendar_service.py — Google Calendar integration via OAuth2
Reuses the same token.json/credentials.json from gmail_service setup.
"""
import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, date, timezone, timedelta
from typing import Optional

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

TOKEN_PATH = os.path.join(os.path.dirname(__file__), '..', 'token.json')
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
]

@dataclass
class CalendarEvent:
    title: str
    start_time: str   # Human-readable e.g. "3:00 PM"
    end_time: str
    date: str         # e.g. "Thursday, May 22"
    attendees: list[str]
    location: Optional[str] = None
    is_all_day: bool = False

def _get_credentials() -> Optional[Credentials]:
    if not os.path.exists(TOKEN_PATH):
        return None
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, 'w') as f:
            f.write(creds.to_json())
    return creds

def _get_calendar_service():
    creds = _get_credentials()
    if not creds:
        raise RuntimeError(
            "Calendar not authenticated. Run: python -m server.utils.google_auth"
        )
    return build('calendar', 'v3', credentials=creds)

def _parse_event(event: dict) -> CalendarEvent:
    title = event.get('summary', 'Untitled Event')
    
    start = event['start']
    end = event['end']
    
    attendees = [
        a.get('displayName') or a.get('email', '')
        for a in event.get('attendees', [])
        if a.get('email') != 'me'
    ]
    
    if 'dateTime' in start:
        is_all_day = False
        start_dt = datetime.fromisoformat(start['dateTime'].replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end['dateTime'].replace('Z', '+00:00'))
        start_str = start_dt.strftime("%I:%M %p").lstrip('0')
        end_str = end_dt.strftime("%I:%M %p").lstrip('0')
        date_str = start_dt.strftime("%A, %B %d")
    else:
        is_all_day = True
        day = date.fromisoformat(start['date'])
        start_str = "All day"
        end_str = "All day"
        date_str = day.strftime("%A, %B %d")

    return CalendarEvent(
        title=title,
        start_time=start_str,
        end_time=end_str,
        date=date_str,
        attendees=attendees,
        location=event.get('location'),
        is_all_day=is_all_day,
    )

def _fetch_events_sync(time_min: str, time_max: str) -> list[CalendarEvent]:
    service = _get_calendar_service()
    result = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime',
        maxResults=20,
    ).execute()
    return [_parse_event(e) for e in result.get('items', [])]

async def get_events_today() -> list[CalendarEvent]:
    today = date.today()
    time_min = datetime(today.year, today.month, today.day, 0, 0, 0).astimezone().isoformat()
    time_max = datetime(today.year, today.month, today.day, 23, 59, 59).astimezone().isoformat()
    return await asyncio.get_event_loop().run_in_executor(
        None, _fetch_events_sync, time_min, time_max
    )

async def get_events_this_week() -> list[CalendarEvent]:
    today = date.today()
    time_min = datetime(today.year, today.month, today.day).astimezone().isoformat()
    time_max = (datetime(today.year, today.month, today.day) + timedelta(days=7)).astimezone().isoformat()
    return await asyncio.get_event_loop().run_in_executor(
        None, _fetch_events_sync, time_min, time_max
    )

async def get_next_event() -> Optional[CalendarEvent]:
    events = await get_events_today()
    now = datetime.now()
    for e in events:
        if not e.is_all_day:
            return e
    return events[0] if events else None

def is_calendar_authenticated() -> bool:
    creds = _get_credentials()
    return creds is not None and creds.valid
