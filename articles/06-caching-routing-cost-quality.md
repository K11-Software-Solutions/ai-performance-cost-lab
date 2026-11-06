# 06. Caching, Routing and the Cost–Quality Trade-off

> **Series:** AI Performance and Cost Lab · [Index](../README.md#articles) · Previous: [05](05-token-budgets-cost-per-resolved-request.md) · Next: [07. Regression Gates That Don't Flap](07-regression-gates-that-dont-flap.md)

Two levers dominate LLM cost: **which model** answers, and whether a model answers at all (caching). Both change quality, so they have to be judged on cost *and* outcome.

## Experiment E3

Six configurations at 2 requests per second (below every configuration's capacity, so this compares cost, not overload), 10 seeds each. The last cost column prices each unresolved request at **$2.50**: an illustrative cost for a human to handle what the assistant did not.

| Configuration | Model cost per request | Resolved | Cost per resolved | Including human handling | p95 | p95 TTFT |
|---|---|---|---|---|---|---|
| route by intent (default) | $0.0043 | 92.4% | $0.0047 | $0.194 | 11.7 s | 0.95 s |
| everything to large | $0.0076 | 92.9% | $0.0082 | **$0.185** | 11.6 s | 1.07 s |
| everything to small | **$0.0004** | **85.6%** | **$0.0004** | $0.360 | **4.7 s** | 0.41 s |
| no cache | $0.0043 | 91.9% | $0.0047 | $0.208 | 11.6 s | 0.93 s |
| prompt bloat | $0.0070 | 92.6% | $0.0075 | $0.191 | 11.8 s | 1.32 s |
| short answers | $0.0034 | 76.6% | $0.0045 | **$0.588** | 6.2 s | 0.94 s |

## Reading it

**Model cost and total cost point in different directions.** Sending everything to the small model is twelve times cheaper in model spend and over twice as fast. It also leaves one request in seven unresolved. Once a human has to pick those up, it is the second **most** expensive option. Model spend is usually a small share of what a support interaction costs; resolution dominates.

**Routing earns its keep in model spend, not in total cost here.** Routing by intent costs 43% less in model spend than sending everything to the large model, at essentially the same resolution. With human handling priced in, the two are within a cent of each other, and the 0.5-point resolution difference between them is within the noise of 10 seeds. The honest conclusion: routing saves money **without losing quality**; it does not create quality.

**Short answers are the trap.** They look like the best performance change in the table (p95 6.2 s instead of 11.7 s, lower spend), and they are the worst outcome by far once unresolved requests are priced. A performance dashboard alone would have approved this change.

**The cache saves less than you might hope.** With 30% of simple questions repeated, about 10–16% of requests are served from cache. That saves little spend (cached questions are the cheap, simple ones) and little p95 (the tail is long answers, which don't repeat), but it does take load off the models, which matters most near the rate limits. Measure the hit rate on your own traffic before you build one.

## How to test these levers

1. **Always report cost next to resolution**, from the same run. A cost change without its quality change is half a result.
2. **Price failure explicitly**, even roughly. The ranking of options can flip, as it does here.
3. **Test routing with the mix of intents you actually get.** Routing is only as good as the classifier deciding what is "simple"; a misrouted complex request is a cheap failure.
4. **Re-run the comparison when prices change.** Model prices fall often; the right routing threshold moves with them.

## Takeaways

- **The cheapest model per call can be the most expensive per customer.**
- **Routing saves spend without costing quality when the simple and complex cases are separated well.**
- **A faster, cheaper change that resolves fewer requests is a regression.**
- **Caching helps capacity more than cost when repeats are cheap questions.**
