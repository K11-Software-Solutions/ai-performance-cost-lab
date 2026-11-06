"""Simulated LLM endpoints: how long a call takes and what it costs.

Latency of an LLM call is driven by tokens:

    time to first token  = base TTFT + prefill time per input token
    total time           = TTFT + decode time per output token

Real latencies are noisy and have a long tail, so each call gets lognormal noise and,
rarely, a slow outlier. Prices are per 1,000 tokens, input and output priced separately.

The two models and their prices are ILLUSTRATIVE, chosen to have realistic ratios
(a large model several times slower and over ten times more expensive than a small
one). Replace them with your provider's numbers before drawing conclusions about cost.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ModelSpec:
    name: str
    ttft_ms: float                 # base time to first token
    prefill_ms_per_1k: float       # extra TTFT per 1,000 input tokens
    decode_ms_per_token: float     # time per output token
    price_in_per_1k: float         # USD per 1,000 input tokens
    price_out_per_1k: float        # USD per 1,000 output tokens
    context_window: int            # max input + output tokens
    slots: int                     # concurrent requests the endpoint serves
    rpm: int                       # rate limit: requests per minute
    tpm: int                       # rate limit: tokens per minute
    noise_sigma: float = 0.25      # lognormal spread
    tail_prob: float = 0.02        # chance of a slow outlier
    tail_factor: float = 4.0

    def ttft(self, tokens_in: int) -> float:
        return self.ttft_ms + self.prefill_ms_per_1k * tokens_in / 1000

    def service_ms(self, tokens_in: int, tokens_out: int, rng: random.Random) -> tuple[float, float]:
        """(time to first token, total time) for one call, with noise."""
        noise = math.exp(rng.gauss(0, self.noise_sigma) - self.noise_sigma ** 2 / 2)   # mean 1
        if rng.random() < self.tail_prob:
            noise *= self.tail_factor
        first = self.ttft(tokens_in) * noise
        return first, first + self.decode_ms_per_token * tokens_out * noise

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return self.price_in_per_1k * tokens_in / 1000 + self.price_out_per_1k * tokens_out / 1000

    def slower(self, factor: float) -> "ModelSpec":
        return replace(self, ttft_ms=self.ttft_ms * factor, decode_ms_per_token=self.decode_ms_per_token * factor)


SMALL = ModelSpec("small", ttft_ms=200, prefill_ms_per_1k=40, decode_ms_per_token=6,
                  price_in_per_1k=0.00015, price_out_per_1k=0.0006, context_window=16_000,
                  slots=32, rpm=3000, tpm=2_000_000)
LARGE = ModelSpec("large", ttft_ms=500, prefill_ms_per_1k=120, decode_ms_per_token=15,
                  price_in_per_1k=0.003, price_out_per_1k=0.015, context_window=128_000,
                  slots=32, rpm=1000, tpm=500_000)
MODELS = {m.name: m for m in (SMALL, LARGE)}
