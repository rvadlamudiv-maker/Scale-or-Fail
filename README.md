# Scale or Fail

**Survive the outages that took down the internet.** A system design game with a deterministic Python simulation engine.

Players design an architecture, then replay scenarios inspired by real, publicly documented outages. Failures emerge from the simulation instead of being scripted.

> Status: Day 2 - queues, latency, timeouts, end-to-end p50/p99, validated against queueing theory.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m engine.cli run scenarios/url_shortener.yaml designs/starter.yaml
pytest -v
```

## How the engine works

- A **design** is a validated directed acyclic graph of components (`designs/*.yaml`).
- A **scenario** defines traffic: base load, spikes, seeded noise (`scenarios/*.yaml`).
- The simulator advances in fixed ticks (10 Hz). Traffic flows through the graph in topological order as rates, which keeps it fast at millions of simulated requests per second.
- Load balancers split traffic by weight; other components fan out to each dependency.
- Runs are deterministic: same design + scenario + seed = identical result.

## The math

| Behavior | Model |
|---|---|
| Queues | Requests a node can't serve wait in line (default limit: 1 s of capacity); overflow is dropped |
| Timeouts | Requests that would wait longer than `timeout_ms` give up (fail fast) |
| Processing latency | M/M/1 curve: `service_time / (1 - utilization)`, utilization capped at 0.95 |
| Backlog wait | Little's Law (L = λW): `wait = queue_depth / capacity` |
| End-to-end latency | Load balancers: weighted average of targets. Other nodes: own latency + `calls_per_request × downstream` |
| p50 / p99 | End-to-end latency percentiles across the run, weighted by traffic |

`tests/test_queueing_theory.py` checks the engine against these results: no queue below capacity, linear queue growth when overloaded, drain time = backlog / (capacity − arrivals), the M/M/1 curve, and Little's Law.

## What the starter design teaches

A 15-second viral spike against 4 app servers and 1 database:

- The app tier saturates and 20% of requests time out.
- **Scaling the app tier to 8 instances makes the database worse** (120% → 236% load): fixing one bottleneck moves it downstream.
- **The database recovers last.** While the app drains its backlog, it keeps the database overloaded, so a 15 s spike causes ~30 s of user pain (p99 2.5 s).

## Roadmap

- [x] Day 1 - models, scenarios, simulator, CLI, tests
- [x] Day 2 - queues, latency, timeouts, end-to-end p50/p99, queueing-theory tests
- [ ] Retries, cache, connection pools, replicas, autoscaling, cost
- [ ] Failure physics: metastable failures, tail latency, gray failures, correctness
- [ ] Incident scenarios + Daily Outage
- [ ] Browser game (React Flow + Pyodide)

*Not affiliated with any company referenced in scenarios.*
