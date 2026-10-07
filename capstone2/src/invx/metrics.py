"""Per-document cost/latency logging.

Gemini free tier bills nothing, so cost here is *notional*: tokens x paid-tier rates.
Verify rates against the current pricing page before quoting them (USD per 1M tokens).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# gemini-2.5-flash paid-tier list prices (check ai.google.dev/pricing)
RATES = {"input": 0.30, "cached_input": 0.03, "output": 2.50}


@dataclass
class DocMetrics:
    file: str
    model: str
    attempts: int = 0
    latency_s: float = 0.0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0  # includes thinking tokens
    status: str = ""

    @property
    def notional_cost_usd(self) -> float:
        uncached = max(self.prompt_tokens - self.cached_tokens, 0)
        return (uncached * RATES["input"] + self.cached_tokens * RATES["cached_input"]
                + self.output_tokens * RATES["output"]) / 1_000_000

    def add_usage(self, usage) -> None:
        if usage is None:
            return
        self.prompt_tokens += getattr(usage, "prompt_token_count", 0) or 0
        self.cached_tokens += getattr(usage, "cached_content_token_count", 0) or 0
        self.output_tokens += (getattr(usage, "candidates_token_count", 0) or 0) + (
            getattr(usage, "thoughts_token_count", 0) or 0)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["notional_cost_usd"] = round(self.notional_cost_usd, 6)
        d["latency_s"] = round(self.latency_s, 2)
        return d


def append_jsonl(path: Path, m: DocMetrics) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(m.to_dict()) + "\n")
