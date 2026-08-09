"""
cost_tracker.py — In-memory token cost tracker
Tracks cumulative token usage and estimated cost per model.
Exposed via GET /api/stats endpoint in main.py.
"""
import threading
from dataclasses import dataclass, field
from typing import Dict

# Gemini pricing (per 1M tokens) as of May 2025
_PRICING = {
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro":   {"input": 1.25, "output": 10.00},
}

@dataclass
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0

    @property
    def cost_usd(self) -> float:
        model = "gemini-2.5-flash"  # fallback
        price = _PRICING.get(model, {"input": 0, "output": 0})
        return (self.input_tokens / 1_000_000) * price["input"] + \
               (self.output_tokens / 1_000_000) * price["output"]

class CostTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self._usage: Dict[str, ModelUsage] = {}
        self._total_requests = 0

    def record(self, model: str, input_tokens: int, output_tokens: int):
        with self._lock:
            if model not in self._usage:
                self._usage[model] = ModelUsage()
            u = self._usage[model]
            u.input_tokens += input_tokens
            u.output_tokens += output_tokens
            u.calls += 1
            self._total_requests += 1

    def summary(self) -> dict:
        with self._lock:
            total_cost = 0.0
            models = {}
            for model, usage in self._usage.items():
                price = _PRICING.get(model, {"input": 0, "output": 0})
                cost = (usage.input_tokens / 1_000_000) * price["input"] + \
                       (usage.output_tokens / 1_000_000) * price["output"]
                total_cost += cost
                models[model] = {
                    "calls": usage.calls,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "cost_usd": round(cost, 6),
                }
            return {
                "total_requests": self._total_requests,
                "total_cost_usd": round(total_cost, 6),
                "models": models,
            }

# Global singleton
cost_tracker = CostTracker()
