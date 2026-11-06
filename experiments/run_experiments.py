"""Multi-seed experiments behind the articles' findings.

    python -m experiments.run_experiments           # about a minute; writes experiments/results/

E1  Coordinated omission: closed-loop load tests under-report a stall that open-loop tests see.
E2  Retries: none, immediate, backoff and a retry budget, under a short burst and sustained overload.
E3  Cost and quality: routing, caching, prompt size and output limits, priced per resolved request.
E4  Regression gates: false alarms and detection power of three ways to compare two runs.
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

from perflab.app import AppConfig
from perflab.metrics import bootstrap_ratio_ci, percentile, summarise
from perflab.model import LARGE, SMALL
from perflab.sim import LoadSpec, RetryPolicy, run_load

OUT = Path(__file__).parent / "results"
HUMAN_HANDLING_USD = 2.50       # illustrative cost of a human resolving what the assistant did not


def mean(xs):
    return sum(xs) / len(xs)


def e1_coordinated_omission(seeds=range(20)) -> dict:
    stall = (60_000, 30_000)
    rows = []
    for label, load in (("closed loop, 10 users", LoadSpec(mode="closed", users=10, think_ms=1000)),
                        ("open loop, same average rate", None)):
        for stalled in (False, True):
            p95, p99, worst, hit, n, slow = [], [], [], [], [], []
            for seed in seeds:
                if load is None:          # match the closed loop's achieved rate for this seed
                    closed = run_load(AppConfig(), LoadSpec(mode="closed", users=10, think_ms=1000), seed=seed)
                    spec = LoadSpec(rate_rps=len(closed) / 120, stall=stall if stalled else None)
                else:
                    spec = replace(load, stall=stall if stalled else None)
                recs = run_load(AppConfig(), spec, seed=seed)
                lat = [r.latency_ms for r in recs]
                p95.append(percentile(lat, 95))
                p99.append(percentile(lat, 99))
                worst.append(max(lat))
                slow.append(sum(x > 20_000 for x in lat) / len(lat))
                n.append(len(recs))
                hit.append(sum(1 for r in recs if r.arrival < stall[0] + stall[1] and r.end > stall[0]) / len(recs))
            rows.append({"load": label, "stall": "30 s" if stalled else "none", "requests": round(mean(n)),
                         "share_in_stall_window": round(mean(hit), 3),
                         "share_over_20s": round(mean(slow), 3), "p95_s": round(mean(p95) / 1000, 1),
                         "p99_s": round(mean(p99) / 1000, 1), "max_s": round(mean(worst) / 1000, 1)})
    return {"seeds": len(seeds), "rows": rows}


def e2_retries(seeds=range(20)) -> dict:
    loads = {"short burst (20 rps for 10 s)": (AppConfig(), LoadSpec(rate_rps=5, burst=(50, 10, 20))),
             "sustained overload (all-large, 8 rps)": (AppConfig(routing="all-large"), LoadSpec(rate_rps=8))}
    rows = []
    for label, (cfg, load) in loads.items():
        for policy in ("none", "immediate", "backoff", "budget"):
            stats = [summarise(run_load(cfg, load, RetryPolicy(policy), seed), load.duration_s) for seed in seeds]
            rows.append({"load": label, "retry": policy,
                         "error_rate": round(mean([s["error_rate"] for s in stats]), 4),
                         "calls_per_request": round(mean([s["retry_amplification"] for s in stats]), 2),
                         "p95_s": round(mean([s["latency_p95_ms"] for s in stats]) / 1000, 1),
                         "wasted_cost_share": round(mean([s["wasted_cost_share"] for s in stats]), 3)})
    return {"seeds": len(seeds), "rows": rows}


def e3_cost(seeds=range(10)) -> dict:
    configs = {"route by intent (default)": AppConfig(), "everything to large": AppConfig(routing="all-large"),
               "everything to small": AppConfig(routing="all-small"), "no cache": AppConfig(cache=False),
               "prompt bloat (10 chunks, 8 turns)": AppConfig(k_chunks=10, history_turns=8),
               "short answers (max 300 tokens)": AppConfig(max_output_tokens=300)}
    load = LoadSpec(rate_rps=2)               # below every configuration's capacity: cost, not overload
    rows = []
    for label, cfg in configs.items():
        stats = [summarise(run_load(cfg, load, seed=seed), load.duration_s) for seed in seeds]
        per_req, resolved = mean([s["cost_per_request_usd"] for s in stats]), mean([s["resolution_rate"] for s in stats])
        rows.append({"configuration": label, "cost_per_request_usd": round(per_req, 5),
                     "resolution_rate": round(resolved, 3),
                     "cost_per_resolved_usd": round(mean([s["cost_per_resolved_usd"] for s in stats]), 5),
                     "with_human_handling_usd": round(per_req + (1 - resolved) * HUMAN_HANDLING_USD, 3),
                     "p95_s": round(mean([s["latency_p95_ms"] for s in stats]) / 1000, 1),
                     "ttft_p95_s": round(mean([s["ttft_p95_ms"] for s in stats]) / 1000, 2)})
    return {"seeds": len(seeds), "human_handling_usd": HUMAN_HANDLING_USD, "rows": rows}


def e4_regression_gates(trials: int = 20) -> dict:
    """Same configuration (A/A) and a slower large model (A/B), compared three ways."""
    load = LoadSpec(rate_rps=5)

    def lat(cfg, seeds):
        return [r.latency_ms for s in seeds for r in run_load(cfg, load, seed=s)]

    base_cfg = AppConfig()
    candidates = {"no change (A/A)": base_cfg,
                  "large model 10% slower": AppConfig(models={"small": SMALL, "large": LARGE.slower(1.10)}),
                  "large model 25% slower": AppConfig(models={"small": SMALL, "large": LARGE.slower(1.25)})}
    rows = []
    for label, cand in candidates.items():
        single = pooled = boot = 0
        for t in range(trials):
            b_seeds, c_seeds = [1000 + 3 * t + i for i in range(3)], [5000 + 3 * t + i for i in range(3)]
            b1, c1 = lat(base_cfg, b_seeds[:1]), lat(cand, c_seeds[:1])
            single += percentile(c1, 95) > 1.05 * percentile(b1, 95)
            b3, c3 = lat(base_cfg, b_seeds), lat(cand, c_seeds)
            pooled += percentile(c3, 95) > 1.05 * percentile(b3, 95)
            boot += bootstrap_ratio_ci(b3, c3, n_boot=300, seed=t)[1] > 1.05
        rows.append({"candidate": label, "trials": trials,
                     "single_run_p95_over_5pct": round(single / trials, 2),
                     "three_runs_pooled_p95_over_5pct": round(pooled / trials, 2),
                     "bootstrap_ci_above_5pct": round(boot / trials, 2)})
    return {"rows": rows}


def table(rows: list[dict]) -> list[str]:
    cols = list(rows[0])
    return ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + \
           ["| " + " | ".join(str(r[c]) for c in cols) + " |" for r in rows]


def main() -> int:
    results = {"E1": e1_coordinated_omission(), "E2": e2_retries(), "E3": e3_cost(), "E4": e4_regression_gates()}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "experiments.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    L = ["# Experiment results", "", "Generated by `python -m experiments.run_experiments`. Deterministic: rerunning gives the same numbers.", "",
         f"## E1. Coordinated omission ({results['E1']['seeds']} seeds; a 30 s stall at 60 s)", ""] + table(results["E1"]["rows"])
    L += ["", f"## E2. Retry policies ({results['E2']['seeds']} seeds)", ""] + table(results["E2"]["rows"])
    L += ["", f"## E3. Cost and quality at 2 rps ({results['E3']['seeds']} seeds; unresolved requests cost "
          f"${HUMAN_HANDLING_USD:.2f} each to handle by a human, illustrative)", ""] + table(results["E3"]["rows"])
    L += ["", "## E4. Regression gates: how often each method flags a slowdown (share of trials)", ""] + table(results["E4"]["rows"])
    (OUT / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
