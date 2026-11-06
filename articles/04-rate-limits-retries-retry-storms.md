# 04. Rate Limits, Retries and Retry Storms

> **Series:** AI Performance and Cost Lab · [Index](../README.md#articles) · Previous: [03](03-load-testing-percentiles-ttft-coordinated-omission.md) · Next: [05. Token Budgets and Cost per Resolved Request](05-token-budgets-cost-per-resolved-request.md)

LLM providers limit **requests per minute** and **tokens per minute**, and the token limit usually counts the `max_tokens` you ask for, not what the model ends up writing. Exceed either and you get HTTP 429. What your client does next decides whether a busy moment becomes an outage.

## Four retry policies

| Policy | What it does |
|---|---|
| none | gives up on the first failure |
| immediate | retries straight away, up to 4 times |
| backoff | waits 1 s, 2 s, 4 s, 8 s, each with random jitter, before retrying |
| budget | backoff, but only while retries stay under 10% of first attempts |

## Experiment E2: two kinds of overload

Twenty seeds each. A **short burst** adds 20 requests per second for 10 seconds on top of normal traffic. **Sustained overload** sends everything to the large model at 8 requests per second, well past its token limit, for the whole test.

| Load | Retry | Errors | Calls per request | p95 |
|---|---|---|---|---|
| short burst | none | 4.9% | 1.00 | 11.2 s |
| short burst | immediate | 4.6% | 1.27 | 11.0 s |
| short burst | **backoff** | **0.5%** | 1.24 | 15.8 s |
| short burst | budget | 4.1% | 1.10 | 12.0 s |
| sustained | none | 44% | 1.00 | 8.8 s |
| sustained | immediate | 44% | **3.47** | 8.5 s |
| sustained | backoff | 37% | **3.78** | **27.5 s** |
| sustained | **budget** | 44% | **1.10** | 8.9 s |

## What it shows

**Immediate retries never help.** A rate limiter that just said no will say no again 20 ms later. Immediate retries added 27% more calls during the burst and 247% more under sustained load, for no reduction in errors. This is how a **retry storm** starts: the clients multiply the load on the service that is already overloaded.

**Backoff is for bursts.** Waiting a few seconds, with jitter so clients don't all come back together, lets the rate-limit bucket refill: burst errors fell from 4.9% to 0.5%, at the price of a slower p95 for the requests that had to wait.

**Backoff is not a cure for sustained overload.** It reduced errors a little (44% to 37%) by spreading requests over time, but nearly quadrupled the calls and tripled p95. Under sustained overload, retries just turn errors into latency and load.

**A retry budget is for sustained overload.** Capping retries at 10% of traffic kept calls per request at 1.1. It does not reduce errors (the capacity simply isn't there), but it stops the client making things worse. The same 10% budget was **too tight for the burst**: it ran out before the burst was over.

No single setting is right for both. A sensible default combines them: backoff with jitter for transient trouble, a retry budget large enough for your normal bursts, and **load shedding or a fallback** (a cheaper model, a cached answer, an honest "try again shortly") when the budget is exhausted.

## Testing it

- **Test both shapes**: a short burst and sustained overload. A policy tuned on one can fail on the other.
- **Gate calls per request** (`retry_amplification`), not just error rate: a retry storm can look healthy on errors right up to the moment it isn't.
- **Count tokens against limits the way your provider does**, including `max_tokens`. Lowering `max_tokens` to what answers need raises your effective token limit.
- **Negative control**: CI runs the immediate-retry policy and requires the gate to fail on burst and peak errors.

## Takeaways

- **Never retry immediately after a rate limit.**
- **Backoff with jitter absorbs bursts; a retry budget prevents storms.** You need both.
- **Watch calls per request, not only errors.**
