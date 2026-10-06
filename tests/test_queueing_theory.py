"""The engine checked against queueing theory, not just against itself."""

import pytest

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_scenario

CAPACITY = 1000  # one app instance


def single_server(**app_fields) -> SystemGraph:
    return SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", **app_fields},
        ],
        "edges": [{"source": "client", "target": "app"}],
    })


def app_ticks(base_rps, spikes=None, **app_fields):
    result = Simulator(single_server(**app_fields), make_scenario(base_rps, spikes=spikes)).run()
    return [s.nodes["app"] for s in result.snapshots]


@pytest.mark.parametrize("utilization", [0.1, 0.3, 0.5, 0.7, 0.9, 0.99])
def test_below_capacity_no_queue_ever_forms(utilization):
    ticks = app_ticks(base_rps=utilization * CAPACITY)
    assert max(t.queue_depth for t in ticks) == pytest.approx(0)


def test_latency_rises_with_utilization_and_explodes_near_saturation():
    latencies = [app_ticks(base_rps=u * CAPACITY)[-1].latency_ms for u in (0.2, 0.5, 0.8, 0.9)]
    assert latencies == sorted(latencies)  # monotonic
    assert latencies[-1] / latencies[0] == pytest.approx(8)  # (1 - 0.2) / (1 - 0.9)


@pytest.mark.parametrize("arrival_rps", [1100, 1300, 1500])
def test_overloaded_queue_grows_linearly_at_arrival_minus_capacity(arrival_rps):
    # Queue limit is 1 s of capacity (1,000), so check before it fills.
    ticks = app_ticks(base_rps=arrival_rps, max_queue=1_000_000)
    for second in (1, 2, 3):
        expected = (arrival_rps - CAPACITY) * second
        assert ticks[second * 10 - 1].queue_depth == pytest.approx(expected)


def test_backlog_drains_at_capacity_minus_arrival():
    # 2 s spike at 1,600 rps builds a 1,000 backlog; afterwards 800 rps arrives.
    # Drain time = backlog / (capacity - arrival) = 1,000 / 200 = 5 s.
    spikes = [{"at_s": 2, "duration_s": 2, "multiplier": 2}]
    ticks = app_ticks(base_rps=800, spikes=spikes)
    drained_at = next(i for i in range(40, 100) if ticks[i].queue_depth < 1e-9)
    assert drained_at / 10 == pytest.approx(4 + 5, abs=0.1)


def test_littles_law_holds_while_the_queue_is_full():
    # L = lambda * W: requests waiting = throughput * time each one waits.
    app = app_ticks(base_rps=1500)[-1]
    wait_s = app.queue_depth / CAPACITY
    assert app.queue_depth == pytest.approx(app.served_rps * wait_s)
    assert wait_s == pytest.approx(1.0)  # a full 1-second queue
