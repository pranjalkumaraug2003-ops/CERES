"""
monitor_service.py — Background intelligence monitor
Proactively checks emails and calendar events and pushes alerts to the user.
"""
import asyncio
import base64
from datetime import datetime

_monitor_task = None

async def run_monitor(emit_fn):
    """
    Long-running background task.
    emit_fn(event_type, agent, message, data) — calls manager.emit for the active connection.
    """
    while True:
        try:
            now = datetime.now()
            
            # Morning briefing at 8 AM
            if now.hour == 8 and now.minute == 0:
                await _deliver_briefing(emit_fn)
            
            # Every 10 minutes: check for urgent emails
            await _check_urgent_emails(emit_fn)

        except Exception as e:
            print(f"[Monitor] Error: {e}")
        
        await asyncio.sleep(600)  # Check every 10 minutes


async def _check_urgent_emails(emit_fn):
    try:
        from server.services.gmail_service import search_emails, is_gmail_authenticated
        if not is_gmail_authenticated():
            return
        
        urgent_keywords = "is:unread (subject:urgent OR subject:ASAP OR subject:invoice OR subject:deadline OR subject:important)"
        emails = await search_emails(urgent_keywords, max_results=3)
        
        if emails:
            names = [e.sender for e in emails[:2]]
            msg = f"You have {len(emails)} urgent email{'s' if len(emails) > 1 else ''}"
            if names:
                msg += f" from {' and '.join(names)}"
            msg += ". Would you like me to read them?"
            await emit_fn("proactive_alert", "CERES", msg, {"type": "urgent_email"})
            
            # Phase 4B: Read the alert out loud
            from server.services.voice_service import synthesize_sentence, _split_sentences
            for sentence in _split_sentences(msg):
                wav_bytes = await synthesize_sentence(sentence)
                if wav_bytes:
                    b64_audio = base64.b64encode(wav_bytes).decode('utf-8')
                    await emit_fn("tts_chunk", "CERES", "", {"audio_base64": b64_audio})
            await emit_fn("stream_end", "CERES", "", {})
    except Exception as e:
        print(f"[Monitor] Email check error: {e}")


async def _deliver_briefing(emit_fn):
    try:
        from server.services.gmail_service import get_unread_emails, is_gmail_authenticated
        from server.services.calendar_service import get_events_today, is_calendar_authenticated
        from server.services.model_router import get_flash
        from langchain_core.messages import SystemMessage, HumanMessage

        parts = []
        now = datetime.now()
        parts.append(f"Today is {now.strftime('%A, %B %d')}.")

        if is_gmail_authenticated():
            emails = await get_unread_emails(max_results=5)
            if emails:
                parts.append(f"You have {len(emails)} unread emails.")

        if is_calendar_authenticated():
            events = await get_events_today()
            if events:
                event_names = [e.title for e in events[:3]]
                parts.append(f"You have {len(events)} events today: {', '.join(event_names)}.")
            else:
                parts.append("Your calendar is clear today.")

        briefing_text = " ".join(parts)
        
        llm = get_flash(temperature=0.6)
        response = await llm.ainvoke([
            SystemMessage(content="You are CERES delivering a morning briefing. Make it warm, concise, and spoken. 3 sentences max."),
            HumanMessage(content=f"Deliver this morning briefing naturally: {briefing_text}")
        ])
        
        briefing = response.content
        await emit_fn("proactive_alert", "CERES", briefing, {"type": "morning_briefing"})
        
        # Phase 4B: Read the briefing out loud
        from server.services.voice_service import synthesize_sentence, _split_sentences
        for sentence in _split_sentences(briefing):
            wav_bytes = await synthesize_sentence(sentence)
            if wav_bytes:
                b64_audio = base64.b64encode(wav_bytes).decode('utf-8')
                await emit_fn("tts_chunk", "CERES", "", {"audio_base64": b64_audio})
        await emit_fn("stream_end", "CERES", "", {})

    except Exception as e:
        print(f"[Monitor] Briefing error: {e}")


def start_monitor(emit_fn):
    global _monitor_task
    if _monitor_task is None or _monitor_task.done():
        _monitor_task = asyncio.create_task(run_monitor(emit_fn))
        print("[Monitor] Background intelligence monitor started.")
