# AI Performance and Cost Lab

[![CI quality gates](https://github.com/K11-Software-Solutions/ai-performance-cost-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/K11-Software-Solutions/ai-performance-cost-lab/actions/workflows/ci.yml)
[![Code: MIT](https://img.shields.io/badge/Code-MIT-blue.svg)](LICENSE) [![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24025301.svg)](https://doi.org/10.5281/zenodo.24025301) [![Articles: CC BY 4.0](https://img.shields.io/badge/Articles-CC%20BY%204.0-lightgrey.svg)](articles/LICENSE.md)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![No dependencies](https://img.shields.io/badge/runtime%20deps-none-success)
![No API key needed](https://img.shields.io/badge/API%20key-not%20required-success)

**Load-test an LLM application and gate its speed, spend and outcome together: latency percentiles and time to first token, coordinated omission, rate limits and retry storms, token budgets, cost per resolved request, and regression gates that don't flap.**

The sixth lab in a series for quality engineers moving into AI:

| Lab | Question it answers |
|---|---|
| [Becoming an AI Quality Engineer](https://github.com/K11-Software-Solutions/becoming-ai-quality-engineer) | Is the RAG **application** good enough to ship? |
| [LLM Model Testing Lab](https://github.com/K11-Software-Solutions/llm-model-testing-lab) | Is the **model** good enough? |
| [Agent Testing Lab](https://github.com/K11-Software-Solutions/agent-testing-lab) | Is the **agent** safe to let act? |
| [AI Production Monitoring Lab](https://github.com/K11-Software-Solutions/ai-production-monitoring-lab) | Is it **still** good, for the users we actually have, right now? |
| [Multi-Agent Testing Lab](https://github.com/K11-Software-Solutions/multi-agent-testing-lab) | When **agents work together**, does the team do the right thing, and who broke it when it doesn't? |
| **AI Performance and Cost Lab** (this repo) | Is it **fast enough under load**, and what does each **good answer** cost? |
| [AI Evaluation Science Lab](https://github.com/K11-Software-Solutions/ai-evaluation-science-lab) | Can we **trust the evaluator**, and how sure are we? |
| [AI Data Quality Lab](https://github.com/K11-Software-Solutions/ai-data-quality-lab) | Is the **data** behind it all fit to learn from, test with and retrieve? |
| [AI Security Testing Lab](https://github.com/K11-Software-Solutions/ai-security-testing-lab) | Can an **attacker** make it misbehave, and how sure are we that they can't? |
| [MCP Testing Lab](https://github.com/K11-Software-Solutions/mcp-testing-lab) | Can we trust the **tools our agents plug into**? |
| [AI Assurance Case Lab](https://github.com/K11-Software-Solutions/ai-assurance-case-lab) (capstone) | Can we **sign it off**, on what evidence, and what risk are we accepting? |

## How it works

A **discrete-event simulator** of an LLM-backed support assistant: token-driven latency (time to first token plus decode time, with a slow tail), two models with illustrative prices, concurrency slots, token-bucket rate limits on requests and tokens, client timeouts and retry policies, and injectable stalls and bursts. The application decides the prompt (system prompt, retrieved chunks, history), the model (routing by intent), the output limit, the cache and the budget guards.

Simulated time with real queueing: a two-minute load test of thousands of requests runs in a fraction of a second, the same seed always gives the same result, and no API key is needed. The models, speeds and prices are **illustrative**; the methods carry over, the numbers need calibrating (article 08).

## Articles

| # | Article |
|---|---|
| 01 | [Why Performance and Cost Are Quality for LLM Apps](articles/01-performance-and-cost-are-quality.md) |
| 02 | [A Simulated LLM Service You Can Load-Test](articles/02-a-simulated-llm-service.md) |
| 03 | [Load Testing LLM Apps: Percentiles, TTFT and Coordinated Omission](articles/03-load-testing-percentiles-ttft-coordinated-omission.md) |
| 04 | [Rate Limits, Retries and Retry Storms](articles/04-rate-limits-retries-retry-storms.md) |
| 05 | [Token Budgets and Cost per Resolved Request](articles/05-token-budgets-cost-per-resolved-request.md) |
| 06 | [Caching, Routing and the Cost–Quality Trade-off](articles/06-caching-routing-cost-quality.md) |
| 07 | [Regression Gates That Don't Flap](articles/07-regression-gates-that-dont-flap.md) |
| 08 | [CI Gates, Negative Controls and Limitations](articles/08-ci-gates-negative-controls-limitations.md) |

## Quick start

Requirements: Python 3.11+. No runtime dependencies and no API key.

```bash
git clone https://github.com/K11-Software-Solutions/ai-performance-cost-lab.git
cd ai-performance-cost-lab
python -m venv .venv
source .venv/bin/activate              # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

```bash
pytest                                                      # 33 tests
python -m evals.run_perf_evals                              # 4 load scenarios, SLOs, budgets, baseline regression check
PERF_VARIANT=short-answers python -m evals.run_perf_evals   # faster and cheaper, and the gate must still fail it
python -m experiments.run_experiments                       # the four experiments behind the articles (~30 s)
```

## Repository layout

```text
perflab/
  model.py      latency and price model for two illustrative LLMs; noise with a slow tail
  app.py        the support assistant: prompt, routing, output limit, cache, context and budget guards; workload
  sim.py        discrete-event simulator: open/closed loop, token-bucket rate limits, queues, timeouts,
                retry policies (none, immediate, backoff, budget), stalls and bursts
  metrics.py    percentiles, TTFT, errors, resolution, cost per resolved request, waste; bootstrap comparison
evals/
  run_perf_evals.py   steady, peak, burst and stall scenarios; SLO and budget gates; baseline regression check
  thresholds.json     per-scenario SLOs and budgets
  baseline.json       the accepted baseline run (latencies and costs), for the regression check
experiments/    E1 coordinated omission, E2 retries, E3 cost and quality, E4 regression gates; results committed
tests/          33 tests
articles/       the eight articles
.github/workflows/ci.yml   tests -> perf gates + 5 negative controls -> experiments reproducibility check
```

## What the lab finds

- **Closed-loop load tests under-count outages.** During a 30-second stall, real (open-loop) traffic put 28% of requests in the bad window and 12% over 20 seconds; a closed-loop test sent almost nothing during the stall and reported a p95 13 seconds better.
- **Immediate retries never helped**; they added up to 3.5 calls per request under overload. **Backoff with jitter cut burst errors from 4.9% to 0.5%** but did nothing for sustained overload except multiply load; a **retry budget** kept calls at 1.1 per request.
- **Prompt bloat doubled input tokens and multiplied p95 time to first token nearly fivefold** for no gain in resolution.
- **Cost per request rewards failure.** Shorter answers cut cost by 20% and p95 by half, and resolved 15 points fewer requests. Gate cost per *resolved* request.
- **The cheapest model per call was the second most expensive per customer** once unresolved requests were priced at an illustrative $2.50 each.
- **A single-run p95 regression gate failed one unchanged build in four.** A bootstrap-interval gate had no false alarms but could not see a 10% slowdown with three two-minute runs: choose the smallest regression you care about, then collect enough data to see it.

## CI quality gates

Every push runs three jobs: **tests**; **performance gates** on four load scenarios plus a statistical regression check against the committed baseline, with five negative controls (realistic bad changes that must fail, including one that makes the app faster and cheaper); and an **experiments** job that fails if the results differ from the committed ones.

## Limitations

A simulated service with illustrative numbers, independent noise, no network or client overhead, one model call per interaction, a simple cache and router, and a placeholder cost of human handling. [Article 08](articles/08-ci-gates-negative-controls-limitations.md#limitations) covers each and how to calibrate the method for a real system.

## About

Created by **Kavita Jadhav**, founder of [K11 Software Solutions](https://github.com/K11-Software-Solutions), Senior SDET and AI Quality Engineer working on LLM evaluation, red teaming and agentic QA systems.

**Licences:** code under the [MIT License](LICENSE); the written material in [`articles/`](articles/LICENSE.md) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) (share and adapt with credit).

The service, models, prices and users are simulated and illustrative.

## Citing

Use GitHub's **Cite this repository** button (from [`CITATION.cff`](CITATION.cff)). Each tagged release is archived on Zenodo with its own DOI. Cite the version you used:

> Jadhav, K. (2026). *AI Performance and Cost Lab* (Version v1.0.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.24025302

To refer to the project as a whole (always resolves to the latest version), use the concept DOI: https://doi.org/10.5281/zenodo.24025301
