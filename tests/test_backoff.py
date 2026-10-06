import pytest

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_scenario

# 1,000 requests arrive in the first tick only (then a trickle of 1 rps).
BURST = [{"at_s": 0, "duration_s": 0.1, "multiplier": 1000}]


def dead_server(**edge_fields) -> SystemGraph:
    # Client -> app that can serve almost nothing, so nearly every attempt fails.
    return SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", "capacity_rps": 1, "max_queue": 0},
        ],
        "edges": [{"source": "client", "target": "app", **edge_fields}],
    })


def retries_per_tick(graph, base_rps=1, spikes=BURST):
    snaps = Simulator(graph, make_scenario(base_rps, spikes=spikes)).run().snapshots
    return [s.nodes["app"].retry_rps for s in snaps]


def test_fixed_backoff_retries_at_a_steady_pace():
    r = retries_per_tick(dead_server(retries=3, retry_delay_ms=100))
    assert [r[1] > 900, r[2] > 900, r[3] > 900] == [True, True, True]


def test_exponential_backoff_doubles_the_wait_each_time():
    # Delays of 100, 200, 400 ms: retries land on ticks 1, 1+2=3 and 3+4=7.
    r = retries_per_tick(dead_server(retries=3, retry_delay_ms=100, backoff="exponential"))
    for tick in (1, 3, 7):
        assert r[tick] > 900
    for tick in (2, 4, 5, 6):
        assert r[tick] < 10


def test_jitter_spreads_retries_over_the_delay_window():
    # 500 ms delay with jitter: the burst's retries spread over ticks 1-5 (~200 per tick).
    r = retries_per_tick(dead_server(retries=1, retry_delay_ms=500, jitter=True))
    for tick in range(1, 6):
        assert r[tick] == pytest.approx(200, rel=0.05)


def test_jitter_changes_when_retries_land_not_how_many():
    fixed = retries_per_tick(dead_server(retries=2, retry_delay_ms=300))
    jittered = retries_per_tick(dead_server(retries=2, retry_delay_ms=300, jitter=True))
    assert sum(jittered) == pytest.approx(sum(fixed), rel=0.02)
    assert max(jittered) < max(fixed)  # same retries, smaller peak


def test_retry_budget_caps_retries_at_a_fraction_of_first_attempts():
    # Steady 1,000 rps against a dead server: without a budget, 3 retries quadruple the load.
    unlimited = retries_per_tick(dead_server(retries=3), base_rps=1000, spikes=None)
    budgeted = retries_per_tick(dead_server(retries=3, retry_budget=0.1), base_rps=1000, spikes=None)
    assert unlimited[-1] == pytest.approx(3000, rel=0.01)
    assert budgeted[-1] == pytest.approx(100, rel=0.01)  # 10% of 1,000 first attempts
