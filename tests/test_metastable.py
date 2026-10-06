import math

import pytest

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_scenario

# 800 rps, doubled to 1,600 rps from t=2s to t=4s, against one 1,000 rps app server.
SPIKE = [{"at_s": 2, "duration_s": 2, "multiplier": 2}]


def caller_and_app(app_fields=None, **edge_fields) -> SystemGraph:
    # Client -> app (1 instance: 1,000 rps, 20 ms service time, 1 s queue).
    return SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", **(app_fields or {})},
        ],
        "edges": [{"source": "client", "target": "app", **edge_fields}],
    })


def run(graph, base_rps=800, spikes=None):
    return Simulator(graph, make_scenario(base_rps, spikes=spikes)).run().snapshots


def test_no_wasted_work_while_the_target_is_fast():
    snaps = run(caller_and_app(caller_timeout_ms=1000))
    assert all(s.nodes["app"].wasted_rps < 0.1 for s in snaps)  # 100 ms calls vs a 1 s timeout: ~none


def test_a_backlog_longer_than_the_timeout_wastes_everything_served():
    # 1,500 rps fills the 1-second queue; a 100 ms caller timeout can never be met.
    app = run(caller_and_app(caller_timeout_ms=100), base_rps=1500)[-1].nodes["app"]
    assert app.served_rps == pytest.approx(1000)
    assert app.wasted_rps == pytest.approx(1000)  # the app is busy, but only for nobody


def test_without_a_backlog_lateness_follows_the_exponential_tail():
    # 500 rps: 50% busy, no backlog, latency = 20 / 0.5 = 40 ms. Timeout 80 ms -> late = e^-2.
    app = run(caller_and_app(caller_timeout_ms=80), base_rps=500)[-1].nodes["app"]
    assert app.latency_ms == pytest.approx(40)
    assert app.wasted_rps == pytest.approx(500 * math.exp(-2))


def test_wasted_work_counts_as_failure():
    snap = run(caller_and_app(caller_timeout_ms=100), base_rps=1500)[-1]
    assert snap.success_ratio == pytest.approx(0)


def test_wasted_calls_are_retried():
    app = run(caller_and_app(caller_timeout_ms=100, retries=1), base_rps=1500)[-1].nodes["app"]
    assert app.retry_rps > 0


def test_retries_plus_wasted_work_stay_broken_after_the_spike():
    # The textbook metastable failure: the trigger (spike) ends at 4 s, the outage doesn't.
    snaps = run(caller_and_app(caller_timeout_ms=1000, retries=3), spikes=SPIKE)
    assert snaps[10].success_ratio == pytest.approx(1)  # healthy before the spike
    assert snaps[-1].success_ratio < 0.01  # still down 6 s after the spike ended...
    assert snaps[-1].nodes["app"].inbound_rps == pytest.approx(800 * 4, rel=0.01)  # ...every request tried 4 times


def test_a_retry_budget_breaks_the_loop():
    snaps = run(caller_and_app(caller_timeout_ms=1000, retries=3, retry_budget=0.1), spikes=SPIKE)
    assert snaps[-1].success_ratio > 0.95


def test_load_shedding_breaks_the_loop():
    # The app drops requests that waited 300 ms, so it never finishes work nobody wants.
    graph = caller_and_app({"timeout_ms": 300}, caller_timeout_ms=1000, retries=3)
    assert run(graph, spikes=SPIKE)[-1].success_ratio > 0.95
