import os
import io
import wave
import re
import asyncio
import logging
import base64
import httpx
import num2words
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

def _normalize_text(text: str) -> str:
    """Normalize text by converting digits to words for speech synthesis."""
    if not text:
        return text

    def replace_num(match):
        val_str = match.group(0)
        try:
            is_negative = val_str.startswith("-")
            if is_negative:
                val_str = val_str[1:]
            
            if "." in val_str:
                val = float(val_str)
            else:
                val = int(val_str)
            
            words = num2words.num2words(val)
            if is_negative:
                return "minus " + words
            return words
        except Exception:
            return match.group(0)

    # Match numbers (including decimals and negative signs) not preceded by word characters
    pattern = re.compile(r'(?<!\w)-?\d+(?:\.\d+)?\b')
    text = pattern.sub(replace_num, text)
    
    # Handle symbols
    text = text.replace("%", " percent")
    text = text.replace("°C", " degrees Celsius")
    text = text.replace("°F", " degrees Fahrenheit")
    text = text.replace("°", " degrees")
    
    return text

# ── Feature Flags ─────────────────────────────────────────────────────────────
USE_LOCAL_STT = os.getenv("USE_LOCAL_STT", "false").lower() == "true"
USE_LOCAL_TTS = os.getenv("USE_LOCAL_TTS", "false").lower() == "true"

# Gemini TTS constants
_TTS_SAMPLE_RATE = 24000
_TTS_CHANNELS = 1
_TTS_SAMPLE_WIDTH = 2  # 16-bit = 2 bytes

# Persistent global HTTP client for cloud TTS service to reuse TCP/SSL connection pools
_tts_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(15.0, connect=5.0),
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    follow_redirects=True
)

async def close_tts_client() -> None:
    """Closes the persistent TTS HTTP client."""
    await _tts_http_client.aclose()

# ── Local Models (Lazy Loaded) ────────────────────────────────────────────────
from server.services.whisper_service import _get_whisper_model
_kokoro = None

# Sentence splitter with negative lookbehinds for abbreviations
_SENTENCE_RE = re.compile(
    r'(?<!\bMr)(?<!\bDr)(?<!\bMs)(?<!\bMrs)(?<!\be\.g)(?<!\bi\.e)(?<=[.!?])\s+(?=[A-Z])'
)
_SENT_RE = re.compile(r'(?<=[.!?])\s+')

def _get_kokoro():
    global _kokoro
    if _kokoro is None:
        from kokoro import KPipeline
        _kokoro = KPipeline(lang_code='a')   # 'a' = American English
    return _kokoro

def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


# ── TTS ───────────────────────────────────────────────────────────────────────

def _pcm_to_wav(pcm_data: bytes) -> bytes:
    """Wrap raw PCM bytes in a WAV container so browsers can decode it."""
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wf:
        wf.setnchannels(_TTS_CHANNELS)
        wf.setsampwidth(_TTS_SAMPLE_WIDTH)
        wf.setframerate(_TTS_SAMPLE_RATE)
        wf.writeframes(pcm_data)
    return buffer.getvalue()

def _kokoro_sentence_to_wav(sentence: str) -> bytes:
    """Synthesize one sentence → WAV bytes. Called in thread executor."""
    pipeline = _get_kokoro()
    # voice='af_heart' — warm, neutral female voice
    generator = pipeline(sentence, voice='af_heart', speed=1.0)
    audio_chunks = []
    for _, _, audio in generator:
        audio_chunks.append(audio)

    if not audio_chunks:
        return b''

    import numpy as np
    import soundfile as sf
    combined = np.concatenate(audio_chunks)
    buf = io.BytesIO()
    sf.write(buf, combined, 24000, format='WAV', subtype='PCM_16')
    return buf.getvalue()

async def synthesize_sentence(sentence: str) -> bytes:
    """Async wrapper — runs Kokoro in thread executor to not block event loop.
    Returns wav bytes, or empty bytes if it fails.
    """
    sentence = _normalize_text(sentence)
    if not sentence.strip():
        return b''
        
    if USE_LOCAL_TTS:
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _kokoro_sentence_to_wav, sentence)
        except Exception as e:
            print(f"Kokoro TTS failed for sentence '{sentence}': {e}. Falling back to Gemini.")
    
    # Gemini TTS Fallback
    try:
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.error("[VoiceService] GOOGLE_API_KEY is not configured for cloud TTS fallback.")
            return b''

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": f"Please read this text verbatim. Text: {sentence}"
                        }
                    ]
                }
            ],
            "generationConfig": {
                "responseModalities": ["audio"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": "Charon"
                        }
                    }
                }
            }
        }

        response = await _tts_http_client.post(url, json=payload)
        if response.status_code == 200:
            data = response.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts and "inlineData" in parts[0]:
                    audio_b64 = parts[0]["inlineData"].get("data", "")
                    if audio_b64:
                        return base64.b64decode(audio_b64)
            logger.warning("[VoiceService] Cloud TTS response parsing failed.")
        else:
            logger.error(f"[VoiceService] Cloud TTS HTTP error ({response.status_code}): {response.text}")
    except Exception as e:
        logger.error(f"[VoiceService] Cloud TTS fallback failed: {e}", exc_info=True)
    return b''

async def stream_tts_sentences(
    token_stream,               # async generator of str tokens
    thread_id: str,
    manager,                    # ConnectionManager
    base64_module,
):
    """
    Receives streaming LLM tokens, accumulates into sentences,
    synthesizes and sends each sentence the moment it's complete.
    First audio plays in ~0.5s after first sentence is generated.
    """
    buffer = ""
    sentence_idx = 0

    async for token in token_stream:
        buffer += token
        # Check for sentence boundary
        parts = _SENT_RE.split(buffer, maxsplit=1)
        if len(parts) > 1:
            sentence, buffer = parts[0].strip(), parts[1]
            if sentence:
                wav = await synthesize_sentence(sentence)
                if wav:
                    await manager.emit(thread_id, "tts_chunk", "TTS", "", {
                        "audio_base64": base64_module.b64encode(wav).decode(),
                        "is_last":      False,
                        "sentence_idx": sentence_idx,
                    })
                    sentence_idx += 1

    # Flush remaining buffer
    if buffer.strip():
        wav = await synthesize_sentence(buffer.strip())
        if wav:
            await manager.emit(thread_id, "tts_chunk", "TTS", "", {
                "audio_base64": base64_module.b64encode(wav).decode(),
                "is_last":      True,
                "sentence_idx": sentence_idx,
            })

# Legacy function for full response, mostly unused now if using streaming
async def synthesize_speech(text: str) -> tuple[bytes, str]:
    # Use gemini directly here for legacy full-response fallback if ever needed
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon",
                    )
                )
            ),
        ),
    )
    raw_pcm = response.candidates[0].content.parts[0].inline_data.data
    wav_bytes = _pcm_to_wav(raw_pcm)
    return wav_bytes, "audio/wav"

async def preload_models() -> None:
    """Pre-loads local Whisper and Kokoro models at server startup to prevent first-query latency spike."""
    loop = asyncio.get_event_loop()
    if USE_LOCAL_STT:
        logger.info("[VoiceService] Pre-loading local Whisper model (small.en)...")
        try:
            await loop.run_in_executor(None, _get_whisper_model)
            logger.info("[VoiceService] Local Whisper model loaded successfully.")
        except Exception as e:
            logger.error(f"[VoiceService] Local Whisper pre-load failed: {e}")

    if USE_LOCAL_TTS:
        logger.info("[VoiceService] Pre-loading local Kokoro model...")
        try:
            await loop.run_in_executor(None, _get_kokoro)
            logger.info("[VoiceService] Local Kokoro model loaded successfully.")
        except Exception as e:
            logger.error(f"[VoiceService] Local Kokoro pre-load failed: {e}")
