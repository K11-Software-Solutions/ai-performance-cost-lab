"""The gate runner and the negative controls CI relies on."""
import json

import pytest

from evals import run_perf_evals as ev


def test_gate_rules():
    rules = {"latency_p95_ms": {"max": 10}, "resolution_rate": {"min": 0.9}}
    assert ev.gate("s", {"latency_p95_ms": 11, "resolution_rate": 0.95}, rules) == ["s: latency_p95_ms = 11 > 10"]
    assert ev.gate("s", {"latency_p95_ms": 9, "resolution_rate": 0.8}, rules) == ["s: resolution_rate = 0.8 < 0.9"]


def test_unknown_variant_is_an_error():
    with pytest.raises(SystemExit):
        ev.variant("faster-somehow")


@pytest.mark.parametrize("variant, passes, expected", [
    ("", True, None),
    ("prompt-bloat", False, "tokens_in_per_request"),
    ("all-large", False, "cost_per_resolved_usd"),
    ("slow-model", False, "regression: p95_latency_ratio"),
    ("immediate-retry", False, "burst: error_rate"),
    ("short-answers", False, "resolution_rate"),
])
def test_negative_controls(monkeypatch, tmp_path, variant, passes, expected):
    monkeypatch.setenv("PERF_VARIANT", variant)
    assert (ev.main(["--out", str(tmp_path)]) == 0) is passes
    failures = json.loads((tmp_path / "perf_report.json").read_text(encoding="utf-8"))["gate_failures"]
    if expected:
        assert any(expected in f for f in failures), failures
