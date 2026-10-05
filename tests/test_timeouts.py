import pytest

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_scenario


def app_graph(timeout_ms=None) -> SystemGraph:
    # Client -> app (1 instance: 1,000 rps capacity, 1,000-request queue).
    app = {"id": "app", "type": "app_server"}
    if timeout_ms is not None:
        app["timeout_ms"] = timeout_ms
    return SystemGraph.model_validate({
        "components": [{"id": "client", "type": "client"}, app],
        "edges": [{"source": "client", "target": "app"}],
    })


def last_app_tick(graph, base_rps):
    return Simulator(graph, make_scenario(base_rps=base_rps)).run().snapshots[-1].nodes["app"]


def test_no_timeout_configured_means_no_timeouts():
    app = last_app_tick(app_graph(), base_rps=1500)
    assert app.timed_out_rps == 0
    assert app.dropped_rps == pytest.approx(500)  # the full queue rejects instead


def test_timeout_caps_how_long_requests_wait():
    # 200 ms timeout at 1,000 rps capacity: at most 200 requests can be waiting.
    app = last_app_tick(app_graph(timeout_ms=200), base_rps=1500)
    assert app.queue_depth == pytest.approx(200)
    assert app.timed_out_rps == pytest.approx(500)  # the 500 rps excess gives up
    assert app.dropped_rps == 0  # the queue never fills, so nothing is rejected
    # Saturated processing (20 ms / (1 - 0.95) = 400 ms) + 200 ms max wait = 600 ms.
    assert app.latency_ms == pytest.approx(600)


def test_timeout_longer_than_the_queue_never_fires():
    # The 1,000-request queue (1 s of work) fills before anyone waits 2 s.
    app = last_app_tick(app_graph(timeout_ms=2000), base_rps=1500)
    assert app.timed_out_rps == 0
    assert app.dropped_rps == pytest.approx(500)


def test_requests_are_conserved_with_timeouts():
    sim = Simulator(app_graph(timeout_ms=200), make_scenario(base_rps=2500, noise=0.2))
    prev_queue = 0.0
    for snap in sim.iter_ticks():
        app = snap.nodes["app"]
        arrived = prev_queue + app.inbound_rps * sim.dt
        left = (app.served_rps + app.dropped_rps + app.timed_out_rps) * sim.dt + app.queue_depth
        assert arrived == pytest.approx(left)
        prev_queue = app.queue_depth
