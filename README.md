# Scale or Fail

**Survive the outages that took down the internet.** A system design game with a deterministic Python simulation engine.

Players design an architecture, then replay scenarios inspired by real, publicly documented outages. Failures emerge from the simulation instead of being scripted.

> Status: Day 3 - retries (backoff, jitter, budgets), caches, connection pools, read replicas. 104 tests.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m engine.cli run scenarios/url_shortener.yaml designs/starter.yaml
pytest -q
```

## How the engine works

- A **design** is a validated directed acyclic graph of components (`designs/*.yaml`).
- A **scenario** defines traffic: base load, spikes, seeded noise (`scenarios/*.yaml`).
- The simulator advances in fixed ticks (10 Hz). Traffic flows through the graph in topological order as rates, which keeps it fast at millions of simulated requests per second.
- Runs are deterministic: same design + scenario + seed = identical result.

## The math

| Behavior | Model |
|---|---|
| Queues | Requests a node can't serve wait in line (default limit: 1 s of capacity); overflow is dropped |
| Timeouts | Requests that would wait longer than `timeout_ms` give up (fail fast) |
| Processing latency | M/M/1 curve: `service_time / (1 - utilization)`, utilization capped at 0.95 |
| Backlog wait | Little's Law (L = λW): `wait = queue_depth / capacity` |
| End-to-end latency | Load balancers: weighted average of targets. Other nodes: own latency + `calls_per_request × downstream`. Caches only count downstream on a miss |
| p50 / p99 | End-to-end latency percentiles across the run, weighted by traffic |
| Retries | Failed calls on an edge come back after `retry_delay_ms`, tracked per attempt up to `retries` |
| Backoff / jitter | `exponential` doubles the delay per attempt; jitter spreads each retry evenly over [0, delay] |
| Retry budget | Retries on an edge never exceed `retry_budget` × first attempts |
| Cache hit ratio | TTL cache: a key requested r times/s hits `rT / (1 + rT)`; warms up over `working_set / traffic` seconds after a cold start |
| Connection pools | Little's Law: the highest rate where `rate × latency(rate) = pool_size`; excess calls are rejected |
| Read replicas | Each replica serves its reads **and** replays every write; lag = 10 ms + backlog wait |

`tests/test_queueing_theory.py` checks the engine against queueing theory: no queue below capacity, linear queue growth when overloaded, drain time = backlog / (capacity − arrivals), the M/M/1 curve, and Little's Law.

## What the sample designs teach

All runs: `scenarios/url_shortener.yaml`, a 15-second viral spike (2.5× traffic).

| Design | Lesson |
|---|---|
| `starter` | The app saturates; scaling it 2× makes the DB **worse** (120% → 236%). The DB recovers last: a 15 s spike causes ~30 s of user pain |
| `retry_storm` | 3 retries triple app load (7.8k → 24k rps) while throughput barely moves |
| `retry_backoff`, `retry_jitter` | In a sustained overload, backoff and jitter change *when* retries land, not how many |
| `retry_budget` | A 10% retry budget cuts retries 95% and peak load from 24k to 8.6k rps |
| `cached` | A warm cache (87% hits) lets a small 2,000 rps DB survive the spike at ≤40% load |
| `cached_cold` | Thundering herd: a restarted cache overloads the DB to 228% at **normal** traffic |
| `cached_short_ttl` | A 5 s TTL drops hits to 28%; the DB is overloaded for the whole run |
| `pooled` | A right-sized pool (200) acts as a bulkhead: DB stays at 45 ms, p99 2,551 → 969 ms |
| `pooled_small` | An undersized pool (100) rejects calls at normal traffic while the DB sits at 80% |
| `one_replica` | Moves the bottleneck to the replica (120%) and adds ~1 s of replication lag (stale reads) |
| `two_replicas` | Each replica still replays every write (72%, not 60%), but lag stays at 10 ms; p99 925 ms |

## Known limitations

- Traffic is modeled as rates, not individual requests, so jitter shows its effect on *timing* but not on the collisions between thousands of separate clients that it prevents in real systems.
- Calls to a database primary are treated as writes; reads are routed to replicas explicitly.

## Roadmap

- [x] Day 1 - models, scenarios, simulator, CLI, tests
- [x] Day 2 - queues, latency, timeouts, end-to-end p50/p99, queueing-theory tests
- [x] Day 3 - retries, backoff, jitter, retry budgets, caches, connection pools, read replicas
- [ ] Autoscaling, cost, scoring, chaos events
- [ ] Failure physics: metastable failures, tail latency, gray failures, correctness
- [ ] Incident scenarios + Daily Outage
- [ ] Browser game (React Flow + Pyodide)

*Not affiliated with any company referenced in scenarios.*
