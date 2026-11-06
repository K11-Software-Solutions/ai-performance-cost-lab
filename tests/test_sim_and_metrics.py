"""The simulator (queueing, rate limits, retries, timeouts, stalls) and the metrics."""
import random
from dataclasses import replace

import pytest

from perflab.app import AppConfig, Request
from perflab.metrics import bootstrap_ratio_ci, percentile, summarise
from perflab.model import LARGE, SMALL
from perflab.sim import CACHE_MS, LoadSpec, RetryPolicy, _Endpoint, run_load


def test_same_seed_same_result():
    a = run_load(AppConfig(), LoadSpec(rate_rps=5, duration_s=30), seed=7)
    b = run_load(AppConfig(), LoadSpec(rate_rps=5, duration_s=30), seed=7)
    assert [(r.latency_ms, r.status, r.cost) for r in a] == [(r.latency_ms, r.status, r.cost) for r in b]


def test_token_bucket_admits_a_burst_then_refills():
    ep = _Endpoint(slots=1, rpm=60, tpm=1_000_000)           # 1 request per second, 2 s of burst allowance
    assert ep.admit(0, 10) and ep.admit(0, 10)
    assert not ep.admit(0, 10)
    assert ep.admit(1000, 10)                                 # one second later, one more fits


def test_retry_policies():
    rng = random.Random(0)
    assert RetryPolicy("none").delay(1, rng) is None
    assert RetryPolicy("immediate").delay(1, rng) == 0.0
    b = RetryPolicy("backoff", base_ms=100)
    d1, d3 = b.delay(1, rng), b.delay(3, rng)
    assert 100 <= d1 <= 200 and 400 <= d3 <= 800             # exponential, with full jitter
    assert b.delay(5, rng) is None                            # max_retries = 4
    budget = RetryPolicy("budget", budget=0.1)
    for _ in range(10):
        budget.record(1)
    assert budget.delay(1, rng) is not None
    budget.record(2)
    assert budget.delay(1, rng) is None                       # 1 retry per 10 first attempts used up


def test_cached_answers_are_fast_and_free():
    recs = run_load(AppConfig(), LoadSpec(rate_rps=5, duration_s=60), seed=0)
    cached = [r for r in recs if r.status == "cache"]
    assert cached and all(r.latency_ms == CACHE_MS and r.cost == 0 for r in cached)


def test_overload_causes_rate_limits_and_retries_amplify_it():
    cfg = AppConfig(routing="all-large")
    none = summarise(run_load(cfg, LoadSpec(rate_rps=8, duration_s=60), RetryPolicy("none")), 60)
    imm = summarise(run_load(cfg, LoadSpec(rate_rps=8, duration_s=60), RetryPolicy("immediate")), 60)
    assert none["status"].get("rate_limited", 0) > 0
    assert imm["retry_amplification"] > 2 * none["retry_amplification"]


def test_timed_out_work_is_still_billed():
    cfg = AppConfig(models={"small": SMALL, "large": LARGE.slower(4)})
    s = summarise(run_load(cfg, LoadSpec(rate_rps=3, duration_s=60, timeout_ms=10_000), RetryPolicy("none")), 60)
    assert s["status"].get("timeout", 0) > 0 and s["wasted_cost_share"] > 0


def test_a_stall_delays_requests_in_flight_and_queued():
    calm = run_load(AppConfig(), LoadSpec(rate_rps=3, duration_s=60), seed=2)
    stalled = run_load(AppConfig(), LoadSpec(rate_rps=3, duration_s=60, stall=(20_000, 10_000)), seed=2)
    assert percentile([r.latency_ms for r in stalled], 99) > percentile([r.latency_ms for r in calm], 99)


def test_closed_loop_sends_less_during_a_stall():
    spec = LoadSpec(mode="closed", users=10, duration_s=120)
    calm = run_load(AppConfig(), spec, seed=1)
    stalled = run_load(AppConfig(), replace(spec, stall=(30_000, 40_000)), seed=1)
    assert len(stalled) < len(calm)                           # the users waited instead of sending


def test_burst_adds_traffic_only_in_its_window():
    spec = LoadSpec(rate_rps=2, duration_s=60, burst=(20, 10, 20))
    arrivals = [r.arrival for r in run_load(AppConfig(), spec, seed=0)]
    inside = sum(20_000 <= a < 30_000 for a in arrivals)
    assert inside > 5 * sum(0 <= a < 10_000 for a in arrivals)


def test_percentile_nearest_rank():
    v = list(range(1, 101))
    assert percentile(v, 50) == 50 and percentile(v, 95) == 95 and percentile(v, 100) == 100
    assert percentile([7], 99) == 7


def test_summary_prices_failures():
    recs = run_load(AppConfig(max_output_tokens=300), LoadSpec(rate_rps=3, duration_s=60), seed=0)
    s = summarise(recs, 60)
    assert s["resolution_rate"] < 0.9
    assert s["cost_per_resolved_usd"] > s["cost_per_request_usd"]


def test_bootstrap_ratio():
    rng = random.Random(0)
    a = [rng.lognormvariate(0, 0.5) for _ in range(2000)]
    point, lo, hi = bootstrap_ratio_ci(a, a)
    assert point == pytest.approx(1.0) and lo <= 1.0 <= hi
    slower = [x * 1.5 for x in a]
    assert bootstrap_ratio_ci(a, slower)[1] > 1.3
