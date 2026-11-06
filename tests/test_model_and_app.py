"""The latency and cost model, and the application's decisions."""
import random

import pytest

from perflab.app import INTENTS, AppConfig, Request, answer_ok, plan, workload
from perflab.model import LARGE, SMALL


def req(intent="refund", answer=250, key="k"):
    return Request(1, intent, key, 60, answer)


def test_latency_grows_with_input_and_output_tokens():
    rng = random.Random(0)
    short = [SMALL.service_ms(500, 50, random.Random(i))[1] for i in range(200)]
    long_out = [SMALL.service_ms(500, 500, random.Random(i))[1] for i in range(200)]
    assert sum(long_out) > 2 * sum(short)
    assert LARGE.ttft(4000) > LARGE.ttft(1000) > 0
    first, total = LARGE.service_ms(1000, 100, rng)
    assert 0 < first < total


def test_noise_has_mean_one_and_a_tail():
    rng = random.Random(1)
    totals = [SMALL.service_ms(0, 100, rng)[1] for _ in range(5000)]
    nominal = SMALL.ttft_ms + 100 * SMALL.decode_ms_per_token
    mean = sum(totals) / len(totals)
    assert 0.95 * nominal < mean < 1.2 * nominal              # tail outliers push the mean up a little
    assert max(totals) > 3 * nominal


def test_cost_formula_and_relative_prices():
    assert SMALL.cost(1000, 1000) == pytest.approx(0.00075)
    assert LARGE.cost(1000, 100) > 10 * SMALL.cost(1000, 100)


def test_slower_scales_speed_not_price():
    slow = LARGE.slower(1.3)
    assert slow.decode_ms_per_token == pytest.approx(LARGE.decode_ms_per_token * 1.3)
    assert slow.cost(1000, 100) == LARGE.cost(1000, 100)


def test_prompt_size_is_the_sum_of_its_parts():
    cfg = AppConfig(system_tokens=400, k_chunks=4, chunk_tokens=250, history_turns=2, turn_tokens=150)
    assert cfg.prompt_tokens(req()) == 400 + 1000 + 300 + 60


@pytest.mark.parametrize("routing, intent, model", [
    ("by-intent", "status", "small"), ("by-intent", "refund", "large"),
    ("all-large", "status", "large"), ("all-small", "troubleshoot", "small"),
])
def test_routing(routing, intent, model):
    assert AppConfig(routing=routing).model_for(req(intent)).name == model


def test_long_answers_are_truncated_and_fail():
    p = plan(req(answer=900), AppConfig(max_output_tokens=300), set())
    assert p.truncated and p.tokens_out == 300
    assert not answer_ok(req(answer=900), p, random.Random(0))


def test_context_overflow_and_budget_are_refused_before_calling():
    assert plan(req("status"), AppConfig(k_chunks=80), set()).refused == "context_overflow"
    assert plan(req("refund"), AppConfig(cost_budget_usd=0.001), set()).refused == "over_budget"


def test_cache_hit_costs_nothing():
    p = plan(req(key="popular"), AppConfig(), {"popular"})
    assert p.cached and p.model is None
    assert not plan(req(key="popular"), AppConfig(cache=False), {"popular"}).cached


def test_workload_is_deterministic_and_follows_the_mix():
    a, b = workload(4000, seed=3), workload(4000, seed=3)
    assert a == b
    for intent, (share, *_rest) in INTENTS.items():
        assert abs(sum(r.intent == intent for r in a) / len(a) - share) < 0.03
    repeats = [r for r in a if "popular" in r.question_key]
    assert repeats and all(INTENTS[r.intent][3] for r in repeats)        # only simple intents repeat
