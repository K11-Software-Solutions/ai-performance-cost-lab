# 08. CI Gates, Negative Controls and Limitations

> **Series:** AI Performance and Cost Lab · [Index](../README.md#articles) · Previous: [07](07-regression-gates-that-dont-flap.md)

## The gates

`python -m evals.run_perf_evals` runs four load scenarios, each with three seeds pooled, and checks [`evals/thresholds.json`](../evals/thresholds.json):

| Scenario | Load | Gated |
|---|---|---|
| steady | 5 requests/s | p95 latency, p95 TTFT, errors, resolution, cost per resolved request, input tokens per request, calls per request, wasted spend |
| peak | 9 requests/s | p95 latency, p95 TTFT, errors, resolution |
| burst | +20 requests/s for 10 s | errors, calls per request, p99 latency |
| stall | 10 s pause at 60 s | errors, p95 TTFT |

It then compares steady-load latency and cost with the committed baseline (article 07). Thresholds sit a little above the measured healthy baseline, and cost is gated **per resolved request** (article 05).

## Negative controls

Each is a realistic bad change; CI requires every one to fail:

| Variant | The change | Caught by |
|---|---|---|
| `prompt-bloat` | 10 chunks, 8 history turns | input tokens, TTFT, cost per resolved request |
| `all-large` | routing switched off | latency, errors, cost (token limit exceeded) |
| `slow-model` | large model 30% slower | p95 latency, baseline regression |
| `immediate-retry` | retry policy without backoff | burst and peak errors |
| `short-answers` | `max_output_tokens` = 300 | resolution rate, though latency and cost **improve** |

The last row is the important one: a gate set measuring only speed and spend would have **passed** it.

## Reproducible experiments

The four experiments behind articles 03–07 are deterministic. CI re-runs them and fails if the results differ from [`experiments/results/summary.md`](../experiments/results/summary.md), so every number quoted in these articles can be reproduced from the commit you are reading.

## Limitations

- **Simulated service.** Speeds, prices, limits and quality rates are illustrative. Before trusting any number for your own system, replace `perflab/model.py` with measurements from your provider (TTFT and tokens per second at your prompt sizes, your actual limits and prices) and the quality table with your own eval results.
- **Independent noise.** Real latency is correlated: a slow provider is slow for every request in the same minute. Correlation makes tails heavier and retries less effective than shown here.
- **No network, no client CPU.** Real requests add connection setup, TLS and serialisation time, and load generators can themselves become the bottleneck.
- **One request per interaction.** Agents and multi-turn conversations make several calls per user action; latency and cost compound per call (see the [Multi-Agent Testing Lab](https://github.com/K11-Software-Solutions/multi-agent-testing-lab)).
- **Simple cache and router.** Exact-match caching and intent-based routing. Semantic caches and learned routers have their own error rates and need their own evals.
- **Fixed human cost.** $2.50 per unresolved request is a placeholder for a number your support team can give you.

## Using the method on a real system

1. Measure your real latency distribution and prices; calibrate the model, or skip the simulator and run the same scenarios against a staging endpoint with an **open-loop** load tool.
2. Keep the scenario set: steady, peak, burst and stall.
3. Keep the metric set: p95/p99, TTFT, errors, calls per request, resolution, cost per resolved request, wasted spend.
4. Keep the negative controls as configuration changes you apply in staging: if a known-bad change passes, the gate is not testing what you think.

## Takeaways

- **Gate speed, spend and outcome together.**
- **Prove every gate with a bad change that must fail.**
- **Calibrate before you believe; the method carries over, the numbers don't.**
