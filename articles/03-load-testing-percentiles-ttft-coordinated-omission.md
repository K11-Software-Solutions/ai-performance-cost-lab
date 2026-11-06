# 03. Load Testing LLM Apps: Percentiles, TTFT and Coordinated Omission

> **Series:** AI Performance and Cost Lab · [Index](../README.md#articles) · Previous: [02](02-a-simulated-llm-service.md) · Next: [04. Rate Limits, Retries and Retry Storms](04-rate-limits-retries-retry-storms.md)

## Percentiles, not averages

At steady load the default configuration has a **mean** latency of about 2.9 s and a **p95** of about 11.4 s. Both are true. Only one describes what one request in twenty experiences. LLM latency distributions are heavily skewed: most requests are short questions answered quickly, a minority are long answers from the large model, and a small tail is slowed by queueing or outliers. Report p50, p95 and p99; use the mean only to reason about cost and capacity.

## Time to first token

When answers stream, users judge the wait by the **time to first token** (TTFT), then by reading speed. A 10-second answer that starts after 0.8 s feels responsive; a 3-second answer that shows nothing for 3 s does not. The lab reports p95 TTFT separately and gates it (1.5 s at steady load). It catches problems total latency understates: at steady load, prompt bloat raised p95 total latency by about a quarter but **p95 TTFT nearly fivefold** (0.96 s to 4.7 s), because every extra input token adds prefill time before the first word appears.

## Coordinated omission

Most load tools run **closed-loop**: N virtual users, each sending a request, waiting for the answer, pausing, and sending the next. Real users are **open-loop**: they arrive on their own schedule, whether or not the service is struggling.

The difference only shows when the service stalls. In a closed loop, a stall also stalls the users: they are all waiting, so they stop sending, and the slow period produces very few measurements. The load tool has **coordinated** with the system under test and **omitted** the requests real users would have sent. The term comes from Gil Tene's talks on latency measurement.

Experiment E1 injects a 30-second stall into a two-minute test and compares a closed loop (10 users) with an open loop at the same average rate, over 20 seeds:

| Load test | Stall | Requests | Share sent during the stall window | Requests over 20 s | p95 |
|---|---|---|---|---|---|
| closed loop | none | 307 | 26% | 0.6% | 11.8 s |
| closed loop | 30 s | **229** | **4.5%** | **4.7%** | **19.2 s** |
| open loop | none | 307 | 28% | 0.6% | 11.8 s |
| open loop | 30 s | 307 | 28% | **12.2%** | **32.3 s** |

During the stall, real traffic keeps arriving, so 28% of requests land in the bad window and one in eight takes more than 20 seconds. The closed-loop test sends a quarter fewer requests in total, almost none during the stall, and reports a p95 **13 seconds better** than what users experienced. The max and p99 look similar, because the few requests caught in the stall were slow in both, but the test badly **under-counts how many** users were affected.

## What to do about it

- **Use open-loop (arrival-rate) load generation** for latency SLOs. Most modern tools support it (constant arrival rate executors, request-rate modes).
- **If you must use a closed loop**, measure latency from each request's *intended* send time, not its actual send time, and treat a drop in request count during a test as a red flag, not a quiet period.
- **Inject a stall on purpose** in a test environment and check your load tool's numbers move the way they should. A load test that can't see a stall can't see an outage.

## Takeaways

- **Report p95/p99 and TTFT; the mean hides the experience.**
- **Gate TTFT separately: prompt growth shows there first.**
- **Closed-loop load tests under-count the bad moments.** Drive load by arrival rate.
- **Test your load tool: inject a stall and see if it notices.**
