# 02. A Simulated LLM Service You Can Load-Test

> **Series:** AI Performance and Cost Lab · [Index](../README.md#articles) · Previous: [01](01-performance-and-cost-are-quality.md) · Next: [03. Load Testing LLM Apps](03-load-testing-percentiles-ttft-coordinated-omission.md)

## The pieces

```text
workload ──► app: build prompt, pick model, check cache and budgets ──► simulator
                                                                          │
   client: timeout, retry policy ◄── rate limiter (requests + tokens) ◄──┤
                                     queue ──► model slots (TTFT + decode)
```

| File | What it models |
|---|---|
| [`perflab/model.py`](../perflab/model.py) | Two models (small, large): time to first token, decode speed, noise with a slow tail, prices, context window, concurrency, rate limits |
| [`perflab/app.py`](../perflab/app.py) | The support assistant: prompt assembly, routing, output limit, cache, context and budget checks; a realistic request mix |
| [`perflab/sim.py`](../perflab/sim.py) | Discrete-event simulation: open- and closed-loop load, token-bucket rate limits, FIFO queues, timeouts, retries, stalls and bursts |
| [`perflab/metrics.py`](../perflab/metrics.py) | Percentiles, error, resolution, cost and waste metrics; bootstrap comparison of two runs |

## Latency comes from tokens

```text
time to first token = base TTFT + prefill time × input tokens
total time          = time to first token + decode time × output tokens
```

Each call gets lognormal noise (mean 1) and, with 2% probability, a slow outlier four times longer, which is what gives real latency distributions their tail. The large model is about 2.5× slower per token than the small one and about 20× more expensive per token.

## The application

A request has an **intent** (order status, policy question, refund, troubleshooting), a question and the length of a complete answer. The app turns it into a call:

- **Prompt** = system prompt (400 tokens) + 4 retrieved chunks (250 each) + 2 history turns (150 each) + the question: about 1,500 input tokens.
- **Routing**: simple intents to the small model, complex ones to the large model (or everything to one).
- **Output limit**: answers longer than `max_output_tokens` are **truncated**, and a truncated answer counts as unresolved.
- **Cache**: popular repeated questions are answered from cache in 5 ms for free.
- **Guards**: calls that would overflow the context window, or whose worst case would exceed the per-request cost budget, are refused before any money is spent.

Whether an answer is acceptable depends on the model and the intent: both models handle simple questions equally well, but the small one resolves complex requests only 72% of the time, against 95% for the large one.

## Load, limits and faults

- **Open loop**: requests arrive on a Poisson schedule regardless of how the service is doing. **Closed loop**: a fixed number of virtual users who each wait for an answer before sending again. Article 03 shows why the difference matters.
- **Rate limits**: token buckets for requests per minute and tokens per minute, with two seconds of burst allowance. Providers count `max_tokens` against the token limit, so the app does too.
- **Client**: a 30-second timeout and a retry policy: none, immediate, exponential backoff with jitter, or backoff with a retry budget.
- **Faults**: a **stall** pauses all model processing (a deploy, a GC pause, a provider incident); a **burst** adds extra traffic for a few seconds.
- **Billing**: every attempt is billed when the model finishes it, **even if the client already gave up**: that work is reported as wasted cost.

## A run

```python
from perflab.app import AppConfig
from perflab.sim import LoadSpec, run_load
from perflab.metrics import summarise

records = run_load(AppConfig(), LoadSpec(rate_rps=5, duration_s=120), seed=0)
summarise(records, 120)["latency_p95_ms"]
```

At 5 requests per second the default configuration is healthy: no errors, p95 latency about 11 s (long troubleshooting answers on the large model), time to first token under 1 s at p95, 93% of requests resolved, and about $0.004 per request. Above roughly 10 requests per second the large model's slots and token limit saturate, queues build and latency climbs steeply: that is the knee every load test is looking for.
