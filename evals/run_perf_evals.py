"""Load scenarios, service-level objectives, cost budgets and a regression check against a baseline.

Usage (from the repo root):

    python -m evals.run_perf_evals                          # current configuration, gates on
    PERF_VARIANT=prompt-bloat python -m evals.run_perf_evals  # a known-bad change: must FAIL
    python -m evals.run_perf_evals --update-baseline         # accept the current run as the new baseline

Every scenario is run with several seeds and the results pooled: a single run's p95 is
a noisy estimate, and gates on single runs flap (article 07).

Writes evals/results/perf_report.md and .json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from perflab.app import AppConfig
from perflab.metrics import bootstrap_ratio_ci, summarise
from perflab.model import LARGE, SMALL
from perflab.sim import LoadSpec, RetryPolicy, run_load

HERE = Path(__file__).parent
SEEDS = (0, 1, 2)
SCENARIOS = {
    "steady": LoadSpec(rate_rps=5),
    "peak": LoadSpec(rate_rps=9),
    "burst": LoadSpec(rate_rps=5, burst=(50, 10, 20)),
    "stall": LoadSpec(rate_rps=5, stall=(60_000, 10_000)),
}
REGRESSION_SCENARIO = "steady"
REGRESSION_TOLERANCE = 1.05     # fail only if CONFIDENTLY more than 5% worse


def variant(name: str) -> tuple[AppConfig, RetryPolicy]:
    """Known-bad changes, used as negative controls. '' is the configuration under test."""
    cfg, retry = AppConfig(), RetryPolicy()
    if name == "prompt-bloat":
        cfg.k_chunks, cfg.history_turns = 10, 8
    elif name == "all-large":
        cfg.routing = "all-large"
    elif name == "slow-model":
        cfg.models = {"small": SMALL, "large": LARGE.slower(1.3)}
    elif name == "immediate-retry":
        retry = RetryPolicy("immediate")
    elif name == "short-answers":
        cfg.max_output_tokens = 300
    elif name:
        raise SystemExit(f"unknown PERF_VARIANT '{name}'")
    return cfg, retry


def run_scenario(cfg: AppConfig, retry: RetryPolicy, load: LoadSpec) -> tuple[dict, list]:
    records = []
    for seed in SEEDS:
        records += run_load(cfg, load, replace(retry), seed)
    return summarise(records, load.duration_s * len(SEEDS)), records


def gate(name: str, metrics: dict, rules: dict) -> list[str]:
    out = []
    for metric, rule in rules.items():
        v = metrics[metric]
        if "max" in rule and v > rule["max"]:
            out.append(f"{name}: {metric} = {v:.4g} > {rule['max']}")
        if "min" in rule and v < rule["min"]:
            out.append(f"{name}: {metric} = {v:.4g} < {rule['min']}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-gate", action="store_true")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--out", type=Path, default=HERE / "results")
    args = parser.parse_args(argv)

    name = os.environ.get("PERF_VARIANT", "")
    cfg, retry = variant(name)
    thresholds = json.loads((HERE / "thresholds.json").read_text(encoding="utf-8"))
    results, failures, samples = {}, [], {}
    for scen, load in SCENARIOS.items():
        metrics, records = run_scenario(cfg, retry, load)
        results[scen] = metrics
        samples[scen] = records
        failures += gate(scen, metrics, thresholds.get(scen, {}))

    baseline_path = HERE / "baseline.json"
    current = {"latency_ms": [round(r.latency_ms, 1) for r in samples[REGRESSION_SCENARIO]],
               "cost_usd": [round(r.cost, 7) for r in samples[REGRESSION_SCENARIO]]}
    if args.update_baseline:
        baseline_path.write_text(json.dumps(current), encoding="utf-8")
    base = json.loads(baseline_path.read_text(encoding="utf-8"))
    p95 = bootstrap_ratio_ci(base["latency_ms"], current["latency_ms"])
    cost = bootstrap_ratio_ci(base["cost_usd"], current["cost_usd"], stat=lambda v: sum(v) / len(v))
    regression = {"p95_latency_ratio": p95, "mean_cost_ratio": cost}
    for label, (point, lo, hi) in regression.items():
        if lo > REGRESSION_TOLERANCE:
            failures.append(f"regression: {label} = {point:.3f} (95% CI {lo:.3f}-{hi:.3f}) is confidently above {REGRESSION_TOLERANCE}")

    cols = ["latency_p50_ms", "latency_p95_ms", "latency_p99_ms", "latency_mean_ms", "ttft_p95_ms", "error_rate",
            "resolution_rate", "cache_hit_rate", "retry_amplification", "tokens_in_per_request",
            "cost_per_request_usd", "cost_per_resolved_usd", "wasted_cost_share"]
    L = ["# Performance and cost report", "",
         f"Configuration: {name or 'current'}   seeds pooled per scenario: {len(SEEDS)}", "",
         "| Metric | " + " | ".join(SCENARIOS) + " |", "|---|" + "---|" * len(SCENARIOS)]
    for c in cols:
        L.append(f"| {c} | " + " | ".join(f"{results[s][c]:.4g}" for s in SCENARIOS) + " |")
    L += ["", "## Regression against the committed baseline (steady load)", "",
          "| Ratio (current / baseline) | Point | 95% CI |", "|---|---|---|"]
    for label, (point, lo, hi) in regression.items():
        L.append(f"| {label} | {point:.3f} | {lo:.3f} - {hi:.3f} |")
    L += ["", f"Fails only if the whole interval is above {REGRESSION_TOLERANCE}: a confident slowdown, not noise.", "",
          "## Gate", "", "PASSED" if not failures else "FAILED:\n" + "\n".join(f"- {f}" for f in failures), ""]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "perf_report.md").write_text("\n".join(L), encoding="utf-8")
    (args.out / "perf_report.json").write_text(json.dumps({"variant": name, "results": results,
                                                          "regression": regression, "gate_failures": failures},
                                                         indent=2, default=str), encoding="utf-8")
    print("\n".join(L))
    if failures and not args.no_gate:
        print("Performance gate FAILED", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
