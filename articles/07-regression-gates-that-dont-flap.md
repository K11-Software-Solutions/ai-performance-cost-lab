# 07. Regression Gates That Don't Flap

> **Series:** AI Performance and Cost Lab · [Index](../README.md#articles) · Previous: [06](06-caching-routing-cost-quality.md) · Next: [08. CI Gates, Negative Controls and Limitations](08-ci-gates-negative-controls-limitations.md)

A performance regression gate compares a candidate build with a baseline and fails if the candidate is slower. The common version, "fail if p95 is more than 5% worse than last time", has a problem: **p95 from one run is a noisy number.** A gate built on it fails builds that changed nothing and passes builds that really are slower.

## Experiment E4

Three candidates, 20 trials each, at steady load:

- **A/A**: the candidate is identical to the baseline; any alarm is false.
- **A/B**: the large model is 10% or 25% slower.

Three ways to decide "slower by more than 5%":

| Method | No change (false alarms) | 10% slower (caught) | 25% slower (caught) |
|---|---|---|---|
| one run each, p95 over +5% | **25%** | 55% | 100% |
| three runs pooled, p95 over +5% | 15% | **85%** | 100% |
| three runs pooled, bootstrap 95% CI entirely above +5% | **0%** | 15% | 90% |

## What it shows

**A single-run gate fails one build in four for nothing.** Teams learn to re-run red builds until they go green, and then the gate protects nothing. That is what "flaky performance test" usually means: not a bug in the test, but a decision rule that ignores noise.

**Pooling runs helps both ways.** Three runs per side cut false alarms from 25% to 15% and raised detection of a 10% slowdown from 55% to 85%. More data is the only thing that improves both at once.

**A confidence interval trades sensitivity for trust.** Requiring the whole bootstrap interval of the p95 ratio to lie above 1.05 produced **no** false alarms, and still caught a 25% slowdown nine times in ten, but it caught a 10% slowdown only 15% of the time. With three two-minute runs, a 10% change in p95 is simply within the noise. The gate is honest about that instead of guessing.

How to choose:

- **Pick the smallest slowdown you care about** (that is a product decision, as with effect sizes in any power analysis), then **add data until the gate can see it**: more seeds, longer runs, or more requests per run.
- **Fail on confident regressions; warn on suspected ones.** The lab's report shows the point estimate and interval for every run, so a "probably 8% slower" is visible even when it does not fail the build.
- **Keep the baseline as data, not as one number.** [`evals/baseline.json`](../evals/baseline.json) stores the baseline run's latencies and costs, so the comparison can resample them. Update it deliberately (`--update-baseline`) and review the change like code.

## The lab's gate

CI compares the steady-load scenario (three seeds pooled) against the committed baseline and fails only if the bootstrap 95% interval of the p95 ratio, or of the mean cost ratio, lies entirely above 1.05. The negative control is a 30% slower large model: its interval (about 1.21 to 1.44) is well clear of the line, and the gate fails as it should. Comparing the baseline configuration with itself gives an interval of roughly 0.92 to 1.08: that width is the noise any single comparison has to beat.

## Takeaways

- **One run's p95 is an estimate, not a fact.**
- **Single-run threshold gates flap; flapping gates get ignored.**
- **Decide the smallest regression that matters, then collect enough data to see it.**
- **Gate on confident regressions and report the interval every time.**
