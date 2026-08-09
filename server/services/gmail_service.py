"""
gmail_service.py — Gmail integration via Google API
Uses OAuth2 token stored at server/token.json after first-time auth.

First-time setup:
1. Go to https://console.cloud.google.com
2. Create a project → Enable Gmail API + Calendar API
3. Create OAuth2 Desktop credentials → Download as server/credentials.json
4. Run: python -m server.utils.google_auth
"""
import os
import json
import base64
from email.mime.text import MIMEText
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar',
]

TOKEN_PATH = os.path.join(os.path.dirname(__file__), '..', 'token.json')
CREDS_PATH = os.path.join(os.path.dirname(__file__), '..', 'credentials.json')

@dataclass
class EmailSummary:
    sender: str
    sender_email: str
    subject: str
    preview: str
    timestamp: str
    thread_id: str
    is_unread: bool = True

def _get_credentials() -> Optional[Credentials]:
    if not os.path.exists(TOKEN_PATH):
        return None
    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, 'w') as f:
            f.write(creds.to_json())
    return creds

def _get_gmail_service():
    creds = _get_credentials()
    if not creds:
        raise RuntimeError(
            "Gmail not authenticated. Run: python -m server.utils.google_auth"
        )
    return build('gmail', 'v1', credentials=creds)

def _parse_email(msg: dict) -> EmailSummary:
    headers = {h['name']: h['value'] for h in msg['payload'].get('headers', [])}
    sender_raw = headers.get('From', 'Unknown')

    # Extract display name and email
    if '<' in sender_raw:
        sender_name = sender_raw.split('<')[0].strip().strip('"')
        sender_email = sender_raw.split('<')[1].rstrip('>')
    else:
        sender_name = sender_raw
        sender_email = sender_raw

    # Get plain text preview
    preview = msg.get('snippet', '')[:150]
    
    # Parse date
    date_str = headers.get('Date', '')
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        timestamp = dt.strftime("%I:%M %p")
    except Exception:
        timestamp = date_str[:16]

    is_unread = 'UNREAD' in msg.get('labelIds', [])

    return EmailSummary(
        sender=sender_name,
        sender_email=sender_email,
        subject=headers.get('Subject', '(no subject)'),
        preview=preview,
        timestamp=timestamp,
        thread_id=msg['threadId'],
        is_unread=is_unread,
    )

async def get_emails_today(max_results: int = 20) -> list[EmailSummary]:
    """Fetch all emails received today."""
    from datetime import date
    today = date.today().strftime("%Y/%m/%d")
    return await search_emails(f"after:{today}", max_results=max_results)

async def get_unread_emails(max_results: int = 10) -> list[EmailSummary]:
    return await search_emails("is:unread", max_results=max_results)

async def search_emails(query: str, max_results: int = 10) -> list[EmailSummary]:
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _search_emails_sync, query, max_results)

def _search_emails_sync(query: str, max_results: int) -> list[EmailSummary]:
    service = _get_gmail_service()
    result = service.users().messages().list(
        userId='me', q=query, maxResults=max_results
    ).execute()
    messages = result.get('messages', [])
    emails = []
    for m in messages:
        msg = service.users().messages().get(
            userId='me', id=m['id'], format='metadata',
            metadataHeaders=['From', 'Subject', 'Date']
        ).execute()
        emails.append(_parse_email(msg))
    return emails

async def send_email(to: str, subject: str, body: str) -> bool:
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send_email_sync, to, subject, body)

def _send_email_sync(to: str, subject: str, body: str) -> bool:
    service = _get_gmail_service()
    message = MIMEText(body)
    message['to'] = to
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId='me', body={'raw': raw}).execute()
    return True

def is_gmail_authenticated() -> bool:
    creds = _get_credentials()
    return creds is not None and creds.valid
