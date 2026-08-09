"""
adb_service.py — Android phone integration via ADB
Requires: USB debugging enabled on your Android device + ADB installed on Windows.

Install ADB: https://developer.android.com/tools/releases/platform-tools
Or via Windows: winget install Google.PlatformTools

Usage:
  - Connect phone via USB
  - Enable Developer Options → USB Debugging
  - Authorize the connection on your phone
"""
import asyncio
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional
import json

@dataclass
class SMSMessage:
    sender: str
    body: str
    timestamp: str
    thread_id: str

@dataclass
class WhatsAppMessage:
    sender: str
    body: str
    timestamp: str

@dataclass  
class CallRecord:
    number: str
    name: str
    call_type: str    # "incoming", "outgoing", "missed"
    duration: str
    timestamp: str

def _get_adb_executable() -> str:
    # 1. Check custom path env variable (loaded from .env)
    env_path = os.getenv("ADB_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # 2. Check if 'adb' command is globally available on system PATH
    try:
        subprocess.run(['adb', 'version'], capture_output=True, timeout=2)
        return 'adb'
    except (FileNotFoundError, subprocess.SubprocessError):
        pass

    # 3. Check common Windows paths where ADB might reside
    user_profile = os.environ.get("USERPROFILE", "C:\\Users\\pranj")
    local_app_data = os.environ.get("LOCALAPPDATA", f"{user_profile}\\AppData\\Local")
    
    candidates = [
        os.path.join(user_profile, "Downloads", "platform-tools", "adb.exe"),
        os.path.join(local_app_data, "Android", "Sdk", "platform-tools", "adb.exe"),
        "C:\\platform-tools\\adb.exe",
        "C:\\android-sdk\\platform-tools\\adb.exe",
        "C:\\Android\\platform-tools\\adb.exe",
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
            
    return 'adb' # Fallback

def _run_adb(args: list[str], timeout: int = 10) -> tuple[bool, str]:
    """Run an ADB command, return (success, output)."""
    adb_exe = _get_adb_executable()
    try:
        result = subprocess.run(
            [adb_exe] + args,
            capture_output=True, timeout=timeout
        )
        stdout_str = result.stdout.decode('utf-8', errors='replace')
        return result.returncode == 0, stdout_str.strip()
    except FileNotFoundError:
        return False, "ADB not found. Install Android Platform Tools."
    except subprocess.TimeoutExpired:
        return False, "ADB command timed out."
    except Exception as e:
        return False, str(e)

async def is_device_connected() -> bool:
    loop = asyncio.get_event_loop()
    ok, out = await loop.run_in_executor(None, _run_adb, ['devices'])
    if not ok:
        return False
    lines = [l for l in out.splitlines() if 'device' in l and 'List' not in l and 'offline' not in l]
    return len(lines) > 0

async def get_sms_messages(limit: int = 10) -> list[SMSMessage]:
    """Fetch recent SMS messages via ADB content provider."""
    loop = asyncio.get_event_loop()
    ok, out = await loop.run_in_executor(None, _run_adb, [
        'shell', 'content', 'query',
        '--uri', 'content://sms/inbox',
        '--projection', 'address:body:date',
        '--sort', 'date DESC',
        '--limit', str(limit)
    ])
    if not ok or not out:
        return []

    messages = []
    for line in out.splitlines():
        if 'Row:' in line:
            try:
                parts = dict(p.split('=', 1) for p in line.split(', ') if '=' in p and 'Row' not in p)
                import datetime
                ts = datetime.datetime.fromtimestamp(int(parts.get('date', 0)) / 1000)
                messages.append(SMSMessage(
                    sender=parts.get('address', 'Unknown').strip(),
                    body=parts.get('body', '').strip()[:200],
                    timestamp=ts.strftime('%I:%M %p'),
                    thread_id=parts.get('thread_id', '0').strip(),
                ))
            except Exception:
                continue
    return messages

async def get_whatsapp_messages() -> list[WhatsAppMessage]:
    """Fetch active WhatsApp messages from notifications via dumpsys."""
    loop = asyncio.get_event_loop()
    ok, out = await loop.run_in_executor(None, _run_adb, ['shell', 'dumpsys', 'notification', '--noredact'])
    if not ok or not out:
        return []

    records = re.split(r'NotificationRecord\(', out)
    messages = []
    
    for r in records[1:]:
        if 'pkg=com.whatsapp' in r:
            # Check if group summary
            is_summary = 'GROUP_SUMMARY' in r or 'groupKey=0|com.whatsapp|g:group_key_messages' in r and 'actions=3' not in r
            
            title_match = re.search(r'android\.title=String \((.*?)\)', r)
            text_match = re.search(r'android\.text=String \((.*?)\)', r)
            when_match = re.search(r'when=(\d+)', r)
            
            title = title_match.group(1) if title_match else "Unknown"
            text = text_match.group(1) if text_match else ""
            
            # Skip empty, summary headers like 'WhatsApp', or generic count notifications
            if title == "WhatsApp" or not text or text.strip() == "" or "new messages" in text or "new message" in text:
                continue
                
            import datetime
            ts_str = "Unknown time"
            if when_match:
                try:
                    ts = datetime.datetime.fromtimestamp(int(when_match.group(1)) / 1000)
                    ts_str = ts.strftime('%I:%M %p')
                except Exception:
                    pass
            
            messages.append(WhatsAppMessage(
                sender=title,
                body=text,
                timestamp=ts_str
            ))
            
    # Deduplicate messages by sender and body
    seen = set()
    deduped = []
    for m in messages:
        key = (m.sender, m.body)
        if key not in seen:
            seen.add(key)
            deduped.append(m)
            
    return deduped

async def send_sms(number: str, message: str) -> bool:
    """Send SMS via ADB (uses Android's messaging intent)."""
    loop = asyncio.get_event_loop()
    # This opens the SMS compose intent with pre-filled number and body
    ok, _ = await loop.run_in_executor(None, _run_adb, [
        'shell', 'am', 'start', '-a', 'android.intent.action.SENDTO',
        '-d', f'smsto:{number}',
        '--es', 'sms_body', message,
        '--ez', 'exit_on_sent', 'true'
    ])
    return ok

async def send_whatsapp(contact: str, message: str) -> bool:
    """Send WhatsApp message via ADB intent (opens WhatsApp with message pre-filled)."""
    loop = asyncio.get_event_loop()
    # Encode spaces
    encoded_msg = message.replace(' ', '%20')
    ok, _ = await loop.run_in_executor(None, _run_adb, [
        'shell', 'am', 'start', '-a', 'android.intent.action.VIEW',
        '-d', f'whatsapp://send?text={encoded_msg}',
        '--es', 'phone', contact
    ])
    return ok

async def get_call_log(limit: int = 5) -> list[CallRecord]:
    """Fetch recent call log via ADB."""
    loop = asyncio.get_event_loop()
    ok, out = await loop.run_in_executor(None, _run_adb, [
        'shell', 'content', 'query',
        '--uri', 'content://call_log/calls',
        '--projection', 'number:name:type:duration:date',
        '--sort', 'date DESC',
        '--limit', str(limit)
    ])
    if not ok or not out:
        return []
    
    records = []
    type_map = {'1': 'incoming', '2': 'outgoing', '3': 'missed'}
    for line in out.splitlines():
        if 'Row:' in line:
            try:
                parts = dict(p.split('=', 1) for p in line.split(', ') if '=' in p and 'Row' not in p)
                import datetime
                ts = datetime.datetime.fromtimestamp(int(parts.get('date', 0)) / 1000)
                secs = int(parts.get('duration', 0))
                records.append(CallRecord(
                    number=parts.get('number', 'Unknown').strip(),
                    name=parts.get('name', 'Unknown').strip(),
                    call_type=type_map.get(parts.get('type', '1').strip(), 'incoming'),
                    duration=f"{secs // 60}m {secs % 60}s",
                    timestamp=ts.strftime('%I:%M %p'),
                ))
            except Exception:
                continue
    return records

def is_adb_available() -> bool:
    ok, _ = _run_adb(['version'])
    return ok
