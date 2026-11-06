# 05. Token Budgets and Cost per Resolved Request

> **Series:** AI Performance and Cost Lab · [Index](../README.md#articles) · Previous: [04](04-rate-limits-retries-retry-storms.md) · Next: [06. Caching, Routing and the Cost–Quality Trade-off](06-caching-routing-cost-quality.md)

## Where the money goes

Cost per call = input tokens × input price + output tokens × output price. For a support assistant, input is dominated by things the user never sees:

| Part of the prompt | Tokens (default) |
|---|---|
| system prompt | 400 |
| retrieved chunks (4 × 250) | 1,000 |
| conversation history (2 turns × 150) | 300 |
| the actual question | 20–180 |

Two-thirds of every prompt is retrieval and history. Those are the parts that grow quietly: someone raises `k` from 4 to 10 "to improve recall", someone keeps the whole conversation "for context". Neither change looks like a cost decision. Both are.

## Prompt bloat

The `prompt-bloat` variant uses 10 chunks and 8 history turns. At steady load it:

- more than **doubles input tokens per request** (1,490 to 3,489);
- raises **cost per request by about 60%**;
- **quintuples p95 time to first token** (0.96 s to 4.7 s), since every input token is prefill time before the first word;
- pushes the large model into its **token-per-minute limit** sooner, so errors and retries appear at loads that used to be fine.

And at the quality level this lab models, it buys **nothing**: resolution stays at 0.92–0.93. Unless an eval shows the extra context is needed, it is pure cost. The gates catch it on tokens per request, TTFT and cost per resolved request.

## Cost per request is the wrong number

The obvious cost metric is cost per request. It has a fatal flaw: **failures are cheap**. A request that was rate-limited, refused or truncated costs little or nothing, so when quality collapses, cost per request goes **down**.

In the lab this happens twice:

- **Short answers** (`max_output_tokens` = 300): cost per request falls 20%, p95 latency halves, and **resolution falls 15 points** (93% to 78%) because answers are cut off.
- **Everything to the large model under peak load**: cost per request *drops*, because 40% of requests fail at the rate limit before any tokens are spent.

Gate **cost per resolved request** instead: total spend divided by requests that got an acceptable answer. It rises when quality falls, which is what you want a cost metric to do.

## Budgets as guards

Two guards run **before** any call:

- **Context window**: a prompt plus `max_output_tokens` that would not fit is refused, rather than failing at the provider after queueing.
- **Per-request cost budget**: if the worst case (full prompt, maximum output, chosen model) would exceed the budget, the call is refused. The worst case matters: the provider bills what the model writes, up to the limit you set.

In CI the gates include tokens per request and cost per resolved request at steady load, so a prompt change that doubles spend fails the build the same way a slowdown does.

## Wasted spend

Every attempt is billed when the model finishes it, even if the client has already timed out. The report shows **wasted cost share**: spend on answers nobody was waiting for. It is under 1% at steady load, and it climbs quickly when timeouts and retries pile up. It is gated at 2%.

## Takeaways

- **Most input tokens are context, not question. Watch k and history length like you watch latency.**
- **Prompt growth shows first in time to first token.**
- **Gate cost per resolved request; cost per request rewards failure.**
- **Refuse calls that cannot fit or cannot be afforded, before spending.**
- **Measure what you pay for and throw away.**
