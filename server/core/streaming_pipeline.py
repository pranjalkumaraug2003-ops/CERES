import asyncio
import re
import time
import base64
import logging
from typing import AsyncGenerator, Callable, Any
from server.services.voice_service import synthesize_sentence
from server.core.runtime_state import runtime_state
from server.shared.ws_protocol import WSMessageType
from server.core.event_bus import event_bus

logger = logging.getLogger(__name__)

# Sentence boundary regex with negative lookbehinds for abbreviations
_SENTENCE_BOUNDARY = re.compile(
    r'(?<!\bMr)(?<!\bDr)(?<!\bMs)(?<!\bMrs)(?<!\be\.g)(?<!\bi\.e)(?<=[.!?])\s+(?=[A-Z])'
)
_FALLBACK_BOUNDARY = re.compile(r'(?<=[.!?])\s+')

# Partial-commit thresholds (characters). The first chunk is deliberately small
# so speech STARTS fast; later chunks are larger so the voice doesn't sound
# chopped up. Local TTS synthesis time scales roughly with text length, so this
# trades a slightly shorter opening phrase for a much lower time-to-first-audio.
_FIRST_CHUNK_CHARS = 28
_FIRST_CHUNK_MIN_SPLIT = 12
_CHUNK_CHARS = 60
_CHUNK_MIN_SPLIT = 30


class StreamingPipeline:
    """Processes streamed text tokens from the LLM, groups them into sentences,
    synthesizes speech in real-time, and sends chunks to the client over WebSockets.
    Integrates backpressure boundaries, cancellation checks, and latency instrumentation.
    """
    def __init__(self, generation_id: str, ws_emit: Callable[[WSMessageType, str, str, Any], Any]):
        self.generation_id = generation_id
        self.ws_emit = ws_emit
        
        # Enforce queue backpressure: max 5 sentences in buffer
        self.sentence_queue = asyncio.Queue(maxsize=5)
        self.sentence_idx = 0
        self.is_running = True

        # ── Latency instrumentation ──
        self._t_start = time.time()
        self._t_first_token: float = 0.0
        self._t_first_audio: float = 0.0
        self._total_sentences: int = 0
        self._total_tokens: int = 0

    async def consume_token_stream(self, token_generator: AsyncGenerator[str, None]) -> str:
        """Consumes tokens from the LLM generator, fills the sentence queue, and accumulates full text."""
        buffer = ""
        full_response = ""
        
        # Start background task to run TTS on the queue
        tts_task = asyncio.create_task(self._process_tts_queue())
        
        try:
            async for token in token_generator:
                # Interruption check: discard tokens if generation_id is stale
                if runtime_state.current_generation != self.generation_id:
                    logger.info(f"[StreamingPipeline] Interruption caught. Terminating stream for: {self.generation_id}")
                    break

                # ── First token instrumentation ──
                self._total_tokens += 1
                if self._t_first_token == 0.0:
                    self._t_first_token = time.time()
                    first_token_latency = self._t_first_token - self._t_start
                    logger.info(f"[StreamingPipeline] ⚡ First token in {first_token_latency:.3f}s")

                buffer += token
                full_response += token
                
                # Push text chunk to client instantly
                await self.ws_emit(
                    WSMessageType.TOKEN_CHUNK,
                    message=token,
                    agent="CommunicationAgent",
                    data={"gen_id": self.generation_id}
                )

                # Segment into sentences
                parts = _FALLBACK_BOUNDARY.split(buffer, maxsplit=1)
                if len(parts) > 1:
                    sentence, buffer = parts[0].strip(), parts[1]
                    if sentence:
                        # Enforce backpressure block
                        await self.sentence_queue.put(sentence)
                else:
                    # Partial commit: split at the last safe separator to start TTS early.
                    #
                    # The FIRST chunk uses a much smaller threshold than the rest.
                    # Time-to-first-audio dominates how responsive CERES feels, and
                    # local Kokoro synthesis time scales with text length — so a
                    # short opening phrase gets audio playing seconds sooner, while
                    # later chunks stay long enough to sound natural (and have the
                    # first chunk's playback time to be synthesized in).
                    is_first = self.sentence_idx == 0 and self._t_first_audio == 0.0
                    commit_at = _FIRST_CHUNK_CHARS if is_first else _CHUNK_CHARS
                    min_split = _FIRST_CHUNK_MIN_SPLIT if is_first else _CHUNK_MIN_SPLIT

                    if len(buffer) >= commit_at:
                        split_idx = max(buffer.rfind(" "), buffer.rfind(","))
                        if split_idx > min_split:
                            sentence = buffer[:split_idx].strip()
                            buffer = buffer[split_idx:].strip()
                            if sentence:
                                await self.sentence_queue.put(sentence)

            # Flush residual text buffer at end of stream
            if buffer.strip() and runtime_state.current_generation == self.generation_id:
                await self.sentence_queue.put(buffer.strip())

        except asyncio.CancelledError:
            logger.info(f"[StreamingPipeline] Token consumer cancelled for: {self.generation_id}")
        finally:
            self.is_running = False
            # Push sentinel to terminate background worker task
            await self.sentence_queue.put(None)
            await tts_task

        # ── Log latency summary ──
        total_time = time.time() - self._t_start
        ft = self._t_first_token - self._t_start if self._t_first_token else 0
        fa = self._t_first_audio - self._t_start if self._t_first_audio else 0
        logger.info(
            f"[StreamingPipeline] Summary: "
            f"first_token={ft:.2f}s | first_audio={fa:.2f}s | "
            f"sentences={self._total_sentences} | tokens={self._total_tokens} | "
            f"total={total_time:.2f}s"
        )

        return full_response

    async def _process_tts_queue(self) -> None:
        """Background worker that pulls sentences from the queue, executes Kokoro
        TTS synthesis, and emits base64 audio chunks.
        """
        while True:
            # Prior check: has user interrupted?
            if runtime_state.current_generation != self.generation_id:
                break
                
            try:
                # Retrieve sentence (blocks if empty)
                sentence = await self.sentence_queue.get()
                if sentence is None:
                    self.sentence_queue.task_done()
                    break

                # Post-retrieval check
                if runtime_state.current_generation != self.generation_id:
                    self.sentence_queue.task_done()
                    break

                # Synthesize audio chunk
                tts_start = time.time()
                wav_bytes = await synthesize_sentence(sentence)
                tts_duration = time.time() - tts_start
                
                # Post-synthesis check
                if runtime_state.current_generation != self.generation_id:
                    self.sentence_queue.task_done()
                    break

                if wav_bytes:
                    # ── First audio instrumentation ──
                    if self._t_first_audio == 0.0:
                        self._t_first_audio = time.time()
                        first_audio_latency = self._t_first_audio - self._t_start
                        logger.info(f"[StreamingPipeline] 🔊 First audio in {first_audio_latency:.3f}s (TTS took {tts_duration:.2f}s)")

                    if self.sentence_idx == 0:
                        await self.ws_emit(
                            WSMessageType.TTS_START,
                            message="",
                            agent="TTS",
                            data={"gen_id": self.generation_id}
                        )

                    audio_b64 = base64.b64encode(wav_bytes).decode('utf-8')
                    # Determine if this is the final sentence chunk
                    is_last = self.sentence_queue.empty() and not self.is_running
                    
                    await self.ws_emit(
                        WSMessageType.TTS_CHUNK,
                        message="",
                        agent="TTS",
                        data={
                            "audio_base64": audio_b64,
                            "sentence_index": self.sentence_idx,
                            "is_last": is_last,
                            "gen_id": self.generation_id
                        }
                    )
                    
                    # Notify observability of speech start on first audio chunk
                    if self.sentence_idx == 0:
                        await event_bus.emit("SpeechStarted", {"gen_id": self.generation_id})
                        
                    self.sentence_idx += 1
                    self._total_sentences += 1
                else:
                    logger.warning(f"[StreamingPipeline] TTS returned empty for sentence: '{sentence[:50]}'")

                self.sentence_queue.task_done()
            except Exception as e:
                # Failure Domain resilience: Worker error must not halt the pipeline
                logger.error(f"[StreamingPipeline] TTS worker thread error: {e}", exc_info=True)
                break
