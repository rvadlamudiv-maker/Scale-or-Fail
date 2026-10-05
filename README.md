# Scale or Fail

**Survive the outages that took down the internet.** A system design game with a deterministic Python simulation engine.

Players design an architecture, then replay scenarios inspired by real, publicly documented outages. Failures emerge from the simulation instead of being scripted.

> Status: Day 1 - data models, traffic scenarios, tick-based simulator, CLI, tests.

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

## Roadmap

- [x] Day 1 - models, scenarios, simulator, CLI, tests
- [ ] Queues, latency, timeouts (validated against M/M/1 and Little's Law)
- [ ] Retries, cache, connection pools, replicas, autoscaling, cost
- [ ] Failure physics: metastable failures, tail latency, gray failures, correctness
- [ ] Incident scenarios + Daily Outage
- [ ] Browser game (React Flow + Pyodide)

*Not affiliated with any company referenced in scenarios.*
