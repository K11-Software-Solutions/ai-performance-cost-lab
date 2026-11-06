"""A discrete-event load simulator for the support assistant.

Simulated time, real queueing: a two-minute load test of thousands of requests runs in
well under a second, and the same seed always gives the same result.

    client ──► rate limiter ──► queue ──► model slots ──► response
       ▲  (429 if over RPM/TPM)          (FIFO)   (TTFT + decode)     │
       └──────── retry policy, client timeout ◄────────────────────────┘

Two ways to generate load:

- open:   requests arrive on their own schedule (Poisson), whether or not earlier
          ones have finished. This is how real users behave.
- closed: a fixed number of virtual users, each waiting for its response (plus think
          time) before sending the next. Many load tools work this way, and when the
          service stalls, the users stall with it and stop sending: the slow period
          produces few measurements. This is coordinated omission (article 03).

Server faults: `stall=(start_ms, length_ms)` pauses all model processing, like a
deployment, a GC pause or a provider incident.

Every attempt is billed when the model finishes it, even if the client has already
given up: work done for a request nobody is waiting for is still paid for.
"""
from __future__ import annotations

import heapq
import random
from dataclasses import dataclass, field

from perflab.app import AppConfig, Request, answer_ok, plan

NETWORK_MS = 20.0       # round trip for a rejected call
CACHE_MS = 5.0


@dataclass
class RetryPolicy:
    """none | immediate | backoff (exponential, full jitter) | budget (backoff, plus a retry budget).

    A retry budget allows retries only while they stay below `budget` of all first
    attempts so far. Under a short burst it behaves like backoff; under sustained
    overload it stops the client from multiplying the load it is suffering from.
    """
    name: str = "backoff"
    max_retries: int = 4
    base_ms: float = 1000.0
    budget: float = 0.1
    first_attempts: int = 0
    retries: int = 0

    def record(self, attempt_number: int) -> None:
        if attempt_number == 1:
            self.first_attempts += 1
        else:
            self.retries += 1

    def delay(self, attempt: int, rng: random.Random) -> float | None:
        """Delay before retry number `attempt` (1-based), or None to give up."""
        if self.name == "none" or attempt > self.max_retries:
            return None
        if self.name == "immediate":
            return 0.0
        if self.name == "budget" and self.retries + 1 > self.budget * max(1, self.first_attempts):
            return None
        wait = self.base_ms * 2 ** (attempt - 1)
        return wait + rng.uniform(0, wait)             # exponential backoff with full jitter


@dataclass
class LoadSpec:
    mode: str = "open"              # open | closed
    duration_s: float = 120.0
    rate_rps: float = 5.0           # open loop
    users: int = 10                 # closed loop
    think_ms: float = 1000.0        # closed loop, mean
    timeout_ms: float = 30_000.0
    stall: tuple[float, float] | None = None        # (start_ms, length_ms): all model processing pauses
    burst: tuple[float, float, float] | None = None  # (start_s, length_s, rps): extra open-loop traffic

    def rate_at(self, t_ms: float) -> float:
        if self.burst and self.burst[0] * 1000 <= t_ms < (self.burst[0] + self.burst[1]) * 1000:
            return self.burst[2]
        return self.rate_rps


@dataclass
class Record:
    id: int
    intent: str
    model: str
    arrival: float
    end: float = 0.0
    first_token: float | None = None
    status: str = ""                # ok | cache | rate_limited | timeout | context_overflow | over_budget
    attempts: int = 0
    tokens_in: int = 0              # billed, all attempts
    tokens_out: int = 0
    cost: float = 0.0
    wasted_cost: float = 0.0        # billed for attempts the client had given up on
    quality_ok: bool = False

    @property
    def latency_ms(self) -> float:
        return self.end - self.arrival

    @property
    def ttft_ms(self) -> float | None:
        return None if self.first_token is None else self.first_token - self.arrival

    @property
    def succeeded(self) -> bool:
        return self.status in ("ok", "cache")


BURST_S = 2.0           # rate-limit buckets hold this many seconds of allowance


@dataclass
class _Endpoint:
    """Model slots, a FIFO queue, and token-bucket rate limits for requests and tokens."""
    slots: int
    rpm: int
    tpm: int
    busy: int = 0
    queue: list = field(default_factory=list)
    last: float = 0.0
    req_bucket: float = -1.0
    tok_bucket: float = -1.0

    def admit(self, t: float, tokens: int) -> bool:
        req_cap, tok_cap = self.rpm / 60 * BURST_S, self.tpm / 60 * BURST_S
        if self.req_bucket < 0:
            self.req_bucket, self.tok_bucket = req_cap, tok_cap
        dt = t - self.last
        self.last = t
        self.req_bucket = min(req_cap, self.req_bucket + dt * self.rpm / 60_000)
        self.tok_bucket = min(tok_cap, self.tok_bucket + dt * self.tpm / 60_000)
        if self.req_bucket < 1 or self.tok_bucket < tokens:
            return False
        self.req_bucket -= 1
        self.tok_bucket -= tokens
        return True


class Simulator:
    def __init__(self, cfg: AppConfig, load: LoadSpec, retry: RetryPolicy | None = None, seed: int = 0):
        self.cfg, self.load, self.retry = cfg, load, retry or RetryPolicy()
        self.rng = random.Random(seed)
        self.events: list = []
        self.seq = 0
        self.endpoints = {name: _Endpoint(m.slots, m.rpm, m.tpm) for name, m in cfg.models.items()}
        self.retry.first_attempts = self.retry.retries = 0
        self.cache: set[str] = set()
        self.records: list[Record] = []

    # --- event plumbing -------------------------------------------------------------
    def _at(self, t: float, kind: str, *payload) -> None:
        self.seq += 1
        heapq.heappush(self.events, (t, self.seq, kind, payload))

    def run(self, requests: list[Request]) -> list[Record]:
        load = self.load
        if load.mode == "open":
            t, peak = 0.0, max(load.rate_rps, load.burst[2] if load.burst else 0)
            it = iter(requests)
            while True:                                 # thinning: Poisson arrivals with a varying rate
                t += self.rng.expovariate(peak / 1000)
                if t > load.duration_s * 1000:
                    break
                if self.rng.random() < load.rate_at(t) / peak:
                    r = next(it, None)
                    if r is None:
                        break
                    self._at(t, "arrive", r)
        else:
            it = iter(requests)
            self._next_request = lambda: next(it, None)
            for u in range(load.users):
                self._at(self.rng.uniform(0, load.think_ms), "user_send", u)
        while self.events:
            t, _, kind, payload = heapq.heappop(self.events)
            getattr(self, "_on_" + kind)(t, *payload)
        return self.records

    # --- clients --------------------------------------------------------------------
    def _on_user_send(self, t: float, user: int) -> None:
        if t > self.load.duration_s * 1000:
            return
        r = self._next_request()
        if r is not None:
            self._on_arrive(t, r, user)

    def _on_arrive(self, t: float, r: Request, user: int | None = None) -> None:
        p = plan(r, self.cfg, self.cache)
        rec = Record(r.id, r.intent, "cache" if p.cached else p.model.name, arrival=t)
        self.records.append(rec)
        if p.cached:
            rec.first_token = t + CACHE_MS
            self._finish(t + CACHE_MS, rec, "cache", r, p, user, quality=True)
        elif p.refused:
            self._finish(t + 1, rec, p.refused, r, p, user, quality=False)
        else:
            self._send(t, rec, r, p, user)

    def _send(self, t: float, rec: Record, r: Request, p, user) -> None:
        rec.attempts += 1
        self.retry.record(rec.attempts)
        attempt = {"rec": rec, "req": r, "plan": p, "user": user, "sent": t, "done": False, "n": rec.attempts}
        ep = self.endpoints[p.model.name]
        if not ep.admit(t, p.tokens_in + self.cfg.max_output_tokens):   # providers count max_tokens
            self._at(t + NETWORK_MS, "attempt_failed", attempt, "rate_limited")
            return
        self._at(t + self.load.timeout_ms, "deadline", attempt)
        ep.queue.append(attempt)
        self._dispatch(t, p.model.name)

    def _on_deadline(self, t: float, attempt: dict) -> None:
        if not attempt["done"]:
            attempt["done"] = True
            attempt["timed_out"] = True
            self._retry_or_finish(t, attempt, "timeout")

    def _on_attempt_failed(self, t: float, attempt: dict, status: str) -> None:
        attempt["done"] = True
        self._retry_or_finish(t, attempt, status)

    def _retry_or_finish(self, t: float, attempt: dict, status: str) -> None:
        rec = attempt["rec"]
        if rec.end:                                    # a later outcome already finished it
            return
        delay = self.retry.delay(attempt["n"], self.rng)
        if delay is None:
            self._finish(t, rec, status, attempt["req"], attempt["plan"], attempt["user"], quality=False)
        else:
            self._at(t + delay, "retry", attempt)

    def _on_retry(self, t: float, attempt: dict) -> None:
        self._send(t, attempt["rec"], attempt["req"], attempt["plan"], attempt["user"])

    # --- server ---------------------------------------------------------------------
    def _dispatch(self, t: float, model: str) -> None:
        ep = self.endpoints[model]
        while ep.busy < ep.slots and ep.queue:
            attempt = ep.queue.pop(0)
            ep.busy += 1
            p = attempt["plan"]
            start = t
            first, total = p.model.service_ms(p.tokens_in, p.tokens_out, self.rng)
            end = start + total
            if self.load.stall:
                s0, length = self.load.stall
                s1 = s0 + length
                if s0 <= start < s1:                    # waits for the stall to end
                    start, end = s1, s1 + total
                elif start < s0 < end:                  # paused mid-flight
                    end += length
            first_at = min(start + first, end)
            self._at(end, "server_done", attempt, first_at)

    def _on_server_done(self, t: float, attempt: dict, first_at: float) -> None:
        p, rec = attempt["plan"], attempt["rec"]
        ep = self.endpoints[p.model.name]
        ep.busy -= 1
        cost = p.model.cost(p.tokens_in, p.tokens_out)
        rec.tokens_in += p.tokens_in
        rec.tokens_out += p.tokens_out
        rec.cost += cost
        if attempt.get("timed_out") or rec.end:
            rec.wasted_cost += cost                    # nobody was waiting for this answer
        elif not attempt["done"]:
            attempt["done"] = True
            rec.first_token = first_at
            ok = answer_ok(attempt["req"], p, self.rng)
            if ok:
                self.cache.add(attempt["req"].question_key)
            self._finish(t, rec, "ok", attempt["req"], p, attempt["user"], quality=ok)
        self._dispatch(t, p.model.name)

    def _finish(self, t: float, rec: Record, status: str, r: Request, p, user, quality: bool) -> None:
        rec.end, rec.status, rec.quality_ok = t, status, quality and status in ("ok", "cache")
        if user is not None:
            self._at(t + self.rng.expovariate(1 / self.load.think_ms), "user_send", user)


def run_load(cfg: AppConfig, load: LoadSpec, retry: RetryPolicy | None = None, seed: int = 0,
             requests: list[Request] | None = None) -> list[Record]:
    from perflab.app import workload
    peak = max(load.rate_rps, load.burst[2] if load.burst else 0)
    n = int(peak * load.duration_s * 2) + 100 if load.mode == "open" else int(load.users * load.duration_s) + 100
    return Simulator(cfg, load, retry, seed).run(requests or workload(n, seed))
