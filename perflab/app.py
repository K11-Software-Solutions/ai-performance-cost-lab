"""The application under test: a support assistant that turns a question into an LLM call.

What it decides, per request:
  - the prompt: system prompt + retrieved chunks + conversation history + the question
  - which model: everything to one model, or route simple intents to the small one
  - how many output tokens it allows (max_output_tokens), and what happens if the
    answer needs more (it is truncated, and a truncated answer is a failed answer)
  - whether a cached answer can be served instead of calling a model
  - whether the call fits the context window and the per-request cost budget

Those are exactly the knobs that change latency, cost and quality together, which is
why performance and cost testing of LLM apps is mostly testing configuration.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from perflab.model import LARGE, MODELS, SMALL, ModelSpec

INTENTS = {
    # name: (share of traffic, question tokens, answer tokens needed (mean), simple?)
    "status": (0.40, 20, 60, True),
    "policy": (0.25, 30, 120, True),
    "refund": (0.20, 60, 250, False),
    "troubleshoot": (0.15, 90, 600, False),
}
# Chance the answer is acceptable, by model and intent type. Illustrative.
QUALITY = {("small", True): 0.97, ("small", False): 0.72, ("large", True): 0.97, ("large", False): 0.95}


@dataclass(frozen=True)
class Request:
    id: int
    intent: str
    question_key: str        # identical questions share a key (cacheable)
    question_tokens: int
    answer_tokens: int       # what a complete answer needs


@dataclass
class AppConfig:
    system_tokens: int = 400
    chunk_tokens: int = 250
    k_chunks: int = 4
    history_turns: int = 2
    turn_tokens: int = 150
    max_output_tokens: int = 800
    routing: str = "by-intent"          # by-intent | all-large | all-small
    cache: bool = True
    cost_budget_usd: float = 0.05       # per request; calls predicted to exceed it are refused
    models: dict = field(default_factory=lambda: dict(MODELS))

    def prompt_tokens(self, r: Request) -> int:
        return (self.system_tokens + self.k_chunks * self.chunk_tokens
                + self.history_turns * self.turn_tokens + r.question_tokens)

    def model_for(self, r: Request) -> ModelSpec:
        simple = INTENTS[r.intent][3]
        name = {"all-large": "large", "all-small": "small"}.get(self.routing, "small" if simple else "large")
        return self.models[name]


@dataclass
class Plan:
    """What the app will do for one request before any timing happens."""
    model: ModelSpec | None
    tokens_in: int
    tokens_out: int
    truncated: bool
    refused: str = ""          # "", "context_overflow", "over_budget"
    cached: bool = False


def plan(r: Request, cfg: AppConfig, cache: set[str]) -> Plan:
    if cfg.cache and r.question_key in cache:
        return Plan(None, 0, 0, False, cached=True)
    model = cfg.model_for(r)
    tin = cfg.prompt_tokens(r)
    tout = min(r.answer_tokens, cfg.max_output_tokens)
    if tin + cfg.max_output_tokens > model.context_window:
        return Plan(model, tin, 0, False, refused="context_overflow")
    if model.cost(tin, cfg.max_output_tokens) > cfg.cost_budget_usd:        # worst case must fit the budget
        return Plan(model, tin, 0, False, refused="over_budget")
    return Plan(model, tin, tout, truncated=r.answer_tokens > cfg.max_output_tokens)


def answer_ok(r: Request, p: Plan, rng: random.Random) -> bool:
    if p.cached:
        return True
    if p.truncated or p.refused:
        return False
    return rng.random() < QUALITY[(p.model.name, INTENTS[r.intent][3])]


def workload(n: int, seed: int = 0, repeat_share: float = 0.3) -> list[Request]:
    """n requests with a realistic mix; a share of simple questions are popular repeats."""
    rng = random.Random(seed)
    names = list(INTENTS)
    weights = [INTENTS[i][0] for i in names]
    out = []
    for i in range(n):
        intent = rng.choices(names, weights)[0]
        _, q, a, simple = INTENTS[intent]
        if simple and rng.random() < repeat_share:
            key = f"{intent}:popular-{rng.randrange(10)}"
        else:
            key = f"{intent}:{seed}-{i}"
        answer = max(10, int(rng.lognormvariate(0, 0.5) * a))
        out.append(Request(i, intent, key, q + rng.randrange(0, q), answer))
    return out


__all__ = ["AppConfig", "Plan", "Request", "plan", "answer_ok", "workload", "INTENTS", "SMALL", "LARGE"]
