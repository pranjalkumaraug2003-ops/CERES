import os
import logging
import asyncio
import tempfile
import base64
import httpx
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy loaded faster-whisper model
_whisper_model = None

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        logger.info("[WhisperService] Initializing local faster-whisper model (small.en, cpu, int8)...")
        # small.en: ~3x faster than medium on CPU, minimal accuracy loss for English-only speech.
        # Optimal for realtime assistant usage on i7-13700H without dedicated GPU.
        _whisper_model = WhisperModel("small.en", device="cpu", compute_type="int8")
    return _whisper_model

def _transcribe_local_sync(audio_bytes: bytes) -> str:
    """Synchronous core executed in thread executor to prevent event loop block."""
    model = _get_whisper_model()
    # Write webm bytes to a temporary file for whisper to read
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as temp_file:
        temp_file.write(audio_bytes)
        temp_file.flush()
        temp_path = temp_file.name
        
    try:
        # small.en is English-only; beam_size=1 (greedy) for maximum realtime speed
        segments, _ = model.transcribe(temp_path, beam_size=1)
        transcription = " ".join(segment.text for segment in segments).strip()
        return transcription
    finally:
        try:
            os.unlink(temp_path)
        except Exception as e:
            logger.warning(f"[WhisperService] Failed to clean up temp file {temp_path}: {e}")

async def transcribe_audio_gemini_fallback(audio_bytes: bytes, mime_type: str) -> str:
    """Calls Gemini REST API directly for cloud transcription as fallback."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("[WhisperService] GOOGLE_API_KEY is not configured for cloud fallback.")
        return ""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": audio_base64
                        }
                    },
                    {
                        "text": "Transcribe this audio exactly as spoken. Output ONLY the transcribed text without quotes or explanation. If the audio is empty or unintelligible, just output nothing."
                    }
                ]
            }
        ]
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code == 200:
                result = response.json()
                parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                if parts and "text" in parts[0]:
                    return parts[0]["text"].strip()
            else:
                logger.error(f"[WhisperService] Gemini fallback transcription failed: {response.text}")
    except Exception as e:
        logger.error(f"[WhisperService] Gemini fallback connection failed: {e}", exc_info=True)
    return ""

async def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    """Orchestrates STT using local faster-whisper with automatic fallback to cloud Gemini REST."""
    use_local_stt = os.getenv("USE_LOCAL_STT", "false").lower() == "true"
    
    if use_local_stt:
        try:
            loop = asyncio.get_event_loop()
            transcription = await loop.run_in_executor(None, _transcribe_local_sync, audio_bytes)
            if transcription:
                return transcription
            logger.info("[WhisperService] Local transcription yielded empty text. Attempting Gemini STT.")
        except Exception as e:
            logger.error(f"[WhisperService] Local faster-whisper failed: {e}. Falling back to Gemini cloud STT.")
            
    # Fallback to cloud
    return await transcribe_audio_gemini_fallback(audio_bytes, mime_type)
