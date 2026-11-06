"""Performance and cost metrics, and a statistically honest way to compare two runs.

Percentiles use the nearest-rank method on all requests, including failures, measured
from when the request ARRIVED (not when it was finally sent). Averages are reported
for comparison, never as the headline: one slow tail and a mean can tell opposite stories.
"""
from __future__ import annotations

import math
import random

from perflab.sim import Record


def percentile(values: list[float], q: float) -> float:
    if not values:
        return math.nan
    s = sorted(values)
    k = max(0, min(len(s) - 1, math.ceil(q / 100 * len(s)) - 1))
    return s[k]


def summarise(records: list[Record], duration_s: float) -> dict:
    n = len(records)
    lat = [r.latency_ms for r in records]
    ttft = [r.ttft_ms for r in records if r.ttft_ms is not None]
    ok = [r for r in records if r.succeeded]
    good = [r for r in records if r.quality_ok]
    cost = sum(r.cost for r in records)
    status: dict[str, int] = {}
    for r in records:
        status[r.status] = status.get(r.status, 0) + 1
    return {
        "requests": n,
        "throughput_rps": n / duration_s,
        "latency_p50_ms": percentile(lat, 50), "latency_p95_ms": percentile(lat, 95),
        "latency_p99_ms": percentile(lat, 99), "latency_mean_ms": sum(lat) / n if n else math.nan,
        "ttft_p95_ms": percentile(ttft, 95),
        "error_rate": 1 - len(ok) / n if n else math.nan,
        "resolution_rate": len(good) / n if n else math.nan,
        "cache_hit_rate": status.get("cache", 0) / n if n else math.nan,
        "retry_amplification": sum(r.attempts for r in records) / max(1, sum(1 for r in records if r.attempts)),
        "tokens_in_per_request": sum(r.tokens_in for r in records) / n if n else math.nan,
        "cost_total_usd": cost,
        "cost_per_request_usd": cost / n if n else math.nan,
        "cost_per_resolved_usd": cost / len(good) if good else math.inf,
        "wasted_cost_share": sum(r.wasted_cost for r in records) / cost if cost else 0.0,
        "status": status,
    }


def bootstrap_ratio_ci(a: list[float], b: list[float], stat=lambda v: percentile(v, 95),
                       n_boot: int = 400, seed: int = 0, level: float = 0.95) -> tuple[float, float, float]:
    """Ratio stat(b) / stat(a) with a bootstrap confidence interval.

    Use it to ask "is the candidate (b) really slower than the baseline (a)?" A single
    p95 from each run is a noisy estimate; the interval says how noisy.
    """
    rng = random.Random(seed)
    point = stat(b) / stat(a)
    ratios = sorted(stat([rng.choice(b) for _ in b]) / stat([rng.choice(a) for _ in a]) for _ in range(n_boot))
    lo = ratios[int((1 - level) / 2 * n_boot)]
    hi = ratios[int((1 + level) / 2 * n_boot) - 1]
    return point, lo, hi
