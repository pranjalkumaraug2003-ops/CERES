import os
import time
import json
import uuid
import logging
from typing import Dict, Any, Optional
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

# Base logs directory inside server/logs
LOGS_DIR = os.path.expanduser("~/.gemini/antigravity/logs/traces")


class TraceSpan:
    def __init__(self, name: str, request_id: str):
        self.name = name
        self.request_id = request_id
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.duration: float = 0.0
        self.metadata: Dict[str, Any] = {}

    def start(self) -> None:
        self.start_time = time.time()

    def finish(self, **kwargs) -> None:
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        self.metadata.update(kwargs)


class Trace:
    """Request-scoped tracer with named spans for granular latency profiling.
    
    Usage:
        trace = Trace(request_id="...")
        with trace.span("gemini_tool_decision"):
            ...
        trace.step("first_token")
        trace.finish()
    """
    def __init__(self, request_id: Optional[str] = None):
        self.request_id = request_id or str(uuid.uuid4())
        self.start_time = time.time()
        self.end_time: float = 0.0
        self.spans: Dict[str, TraceSpan] = {}
        self.steps: Dict[str, float] = {}  # name -> timestamp
        self.metadata: Dict[str, Any] = {}

    def start_span(self, name: str) -> TraceSpan:
        span = TraceSpan(name, self.request_id)
        span.start()
        self.spans[name] = span
        return span

    def finish_span(self, name: str, **kwargs) -> None:
        if name in self.spans:
            self.spans[name].finish(**kwargs)

    @contextmanager
    def span(self, name: str, **kwargs):
        span = self.start_span(name)
        try:
            yield span
        finally:
            self.finish_span(name, **kwargs)

    def step(self, name: str) -> None:
        """Record a named timestamp (e.g., 'stt_complete', 'first_token').
        Useful for discrete events that aren't duration spans.
        """
        self.steps[name] = time.time()

    def finish(self, **kwargs) -> None:
        self.end_time = time.time()
        self.metadata.update(kwargs)
        self.save()

    def save(self) -> None:
        """Save trace information as a single JSON line to logs/traces/traces.jsonl."""
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            log_path = os.path.join(LOGS_DIR, "traces.jsonl")
            
            total_duration = self.end_time - self.start_time

            # Build step offsets relative to trace start
            step_offsets = {
                name: round(ts - self.start_time, 4)
                for name, ts in sorted(self.steps.items(), key=lambda x: x[1])
            }

            trace_data = {
                "request_id": self.request_id,
                "timestamp": datetime.fromtimestamp(self.start_time).isoformat(),
                "total_duration": round(total_duration, 4),
                "metadata": self.metadata,
                "steps": step_offsets,
                "spans": {
                    name: {
                        "duration": round(s.duration, 4),
                        "start_offset": round(s.start_time - self.start_time, 4),
                        "metadata": s.metadata
                    }
                    for name, s in self.spans.items()
                }
            }
            
            # Print rich latency breakdown to stdout for developers
            total_perc = self.metadata.get("total_perceived")
            total_perc_str = f" | Perceived: {total_perc:.3f}s" if total_perc is not None else ""
            
            # Build span timing summary
            span_parts = []
            for name, s in self.spans.items():
                span_parts.append(f"{name}={s.duration:.2f}s")
            spans_str = f" | Spans: [{', '.join(span_parts)}]" if span_parts else ""

            # Build step timing summary
            step_parts = []
            for name, offset in step_offsets.items():
                step_parts.append(f"{name}@{offset:.2f}s")
            steps_str = f" | Steps: [{', '.join(step_parts)}]" if step_parts else ""

            # Intent/tool info
            intent = self.metadata.get("intent", "unknown")
            tool_name = self.metadata.get("tool_name", "")
            tool_str = f" | Tool: {tool_name}" if tool_name else ""
            
            error = self.metadata.get("error") or self.metadata.get("unhandled_error")
            error_str = f" | ERROR: {str(error)[:80]}" if error else ""
            
            print(
                f"[Trace] {self.request_id[:8]} | Total: {total_duration:.3f}s{total_perc_str}"
                f" | Intent: {intent}{tool_str}{spans_str}{steps_str}{error_str}"
            )
            
            with open(log_path, "a") as f:
                f.write(json.dumps(trace_data) + "\n")
        except Exception as e:
            # Observability shouldn't crash the query execution (Failure Domain resilience)
            logger.error(f"[Tracer] Failed to save trace log: {e}", exc_info=True)
