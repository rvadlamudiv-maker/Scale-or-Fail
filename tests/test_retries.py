import pytest

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_scenario


def retry_graph(retries, retry_delay_ms=100, capacity_rps=1000) -> SystemGraph:
    # Client -> app. max_queue=0: anything the app can't serve right away fails immediately.
    return SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", "capacity_rps": capacity_rps, "max_queue": 0},
        ],
        "edges": [{"source": "client", "target": "app",
                   "retries": retries, "retry_delay_ms": retry_delay_ms}],
    })


def app_ticks(graph, base_rps):
    return [s.nodes["app"] for s in Simulator(graph, make_scenario(base_rps)).run().snapshots]


def test_no_retries_configured_means_no_retry_traffic(graph):
    result = Simulator(graph, make_scenario(base_rps=9000)).run()
    assert all(t.retry_rps == 0 for s in result.snapshots for t in s.nodes.values())


def test_failed_calls_come_back_as_extra_load():
    ticks = app_ticks(retry_graph(retries=1), base_rps=1500)
    assert ticks[0].retry_rps == 0
    assert ticks[0].dropped_rps == pytest.approx(500)  # 1,500 in, 1,000 capacity
    assert ticks[1].retry_rps == pytest.approx(500)  # ...and those 500 come back
    assert ticks[1].inbound_rps == pytest.approx(2000)


def test_retries_wait_for_the_retry_delay():
    ticks = app_ticks(retry_graph(retries=1, retry_delay_ms=500), base_rps=1500)
    assert all(t.retry_rps == 0 for t in ticks[:5])  # 500 ms = 5 ticks
    assert ticks[5].retry_rps == pytest.approx(500)


@pytest.mark.parametrize("retries", [1, 2, 3])
def test_when_everything_fails_retries_multiply_the_load(retries):
    # A nearly dead server: almost every attempt fails, so each request is tried 1 + retries times.
    ticks = app_ticks(retry_graph(retries=retries, capacity_rps=1), base_rps=1000)
    assert ticks[-1].inbound_rps == pytest.approx(1000 * (1 + retries), rel=0.01)


def test_retries_add_load_but_not_throughput_when_saturated():
    no_retry = app_ticks(retry_graph(retries=0), base_rps=1500)
    with_retry = app_ticks(retry_graph(retries=3), base_rps=1500)
    assert sum(t.served_rps for t in with_retry) == pytest.approx(sum(t.served_rps for t in no_retry))
    assert sum(t.inbound_rps for t in with_retry) > 1.5 * sum(t.inbound_rps for t in no_retry)


def test_requests_are_conserved_with_retries():
    graph = SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", "instances": 2, "timeout_ms": 300},
        ],
        "edges": [{"source": "client", "target": "app", "retries": 2}],
    })
    sim = Simulator(graph, make_scenario(base_rps=3000, noise=0.2))
    prev_queue = 0.0
    for snap in sim.iter_ticks():
        app = snap.nodes["app"]
        arrived = prev_queue + app.inbound_rps * sim.dt
        left = (app.served_rps + app.dropped_rps + app.timed_out_rps) * sim.dt + app.queue_depth
        assert arrived == pytest.approx(left)
        prev_queue = app.queue_depth
