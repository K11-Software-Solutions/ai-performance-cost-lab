# 01. Why Performance and Cost Are Quality for LLM Apps

> **Series:** AI Performance and Cost Lab · [Index](../README.md#articles) · Next: [02. A Simulated LLM Service You Can Load-Test](02-a-simulated-llm-service.md)

This is the sixth lab in a series for quality engineers moving into AI. The earlier labs asked whether answers are right, whether agents act safely and whether a live system stays good. This one asks: **is it fast enough, does it hold up under load, and what does each good answer cost?**

## What is different about LLM performance

Performance testing a web API is a mature discipline. LLM applications break several of its assumptions:

| | Typical web API | LLM application |
|---|---|---|
| Response time | milliseconds, fairly stable | seconds to tens of seconds, set by **how many tokens** go in and come out |
| What users feel | total time | **time to first token** when streaming, then reading speed |
| Capacity limits | CPU, connections | provider **rate limits** on requests *and* tokens per minute, plus concurrency |
| Cost per request | tiny, roughly fixed | real money, varying 10–100× with prompt size, answer length and model choice |
| A cheaper change | is just better | may cut quality: shorter answers are faster, cheaper and **wrong** |
| A failed request | costs nothing | still costs the tokens processed, and a retry costs them again |

The last two rows are why performance and cost belong in a quality engineer's job. Almost every lever that makes an LLM app faster or cheaper also changes **what the user gets**.

## Four questions this lab answers

1. **How slow is it, really?** Percentiles, not averages; time to first token as well as total time; and load tests that don't hide the worst moments (article 03).
2. **What happens at the limits?** Rate limits, bursts, retries and retry storms (article 04).
3. **What does a good answer cost?** Token budgets, prompt bloat and cost **per resolved request**, not per request (articles 05 and 06).
4. **Did this change make it worse?** Regression gates that catch real slowdowns without failing the build on noise (article 07).

## Why a simulator

The lab load-tests a **simulated** LLM service: discrete-event simulation with real queueing, token-driven latency, rate limits and prices. That choice is deliberate:

- **Repeatable.** The same seed gives the same result, so a failing test points at a cause, not at a noisy afternoon.
- **Fast and free.** A two-minute load test of thousands of requests takes a fraction of a second and no API spend. Every experiment in these articles runs in under a minute on a laptop.
- **Controllable.** You can inject a 30-second stall, a traffic burst or a 25% slower model and know exactly what changed.

The price is realism. The models, speeds and prices are **illustrative**, chosen to have realistic ratios. Article 08 explains what to change before you trust any number for your own system. The methods (what to measure, how to load-test, how to gate) carry over unchanged.

## Takeaways

- **For LLM apps, latency and cost are driven by tokens**, and both are product decisions.
- **Measure what users feel:** tail latency and time to first token.
- **Price every outcome, including failures.**
- **A performance win that lowers quality is a regression.**
