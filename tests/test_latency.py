import pytest

from engine.simulator import Simulator
from tests.conftest import make_graph, make_scenario

APP_SERVICE_MS = 20  # default app server service time


def app_after_run(app_instances, base_rps, spikes=None):
    return Simulator(make_graph(app_instances=app_instances), make_scenario(base_rps, spikes=spikes)).run()


def test_nearly_idle_node_takes_its_service_time():
    app = app_after_run(app_instances=1, base_rps=1).snapshots[-1].nodes["app"]
    assert app.latency_ms == pytest.approx(APP_SERVICE_MS, rel=0.01)


@pytest.mark.parametrize("rps, expected_ms", [(500, 40), (800, 100), (900, 200)])
def test_latency_follows_the_mm1_curve(rps, expected_ms):
    # One app instance = 1,000 rps capacity, so rho = rps / 1000 and latency = S / (1 - rho).
    app = app_after_run(app_instances=1, base_rps=rps).snapshots[-1].nodes["app"]
    assert app.latency_ms == pytest.approx(expected_ms)


def test_backlog_wait_obeys_littles_law():
    # 2 instances: 2,000 rps capacity, queue fills to 2,000 under 3,000 rps of traffic.
    app = app_after_run(app_instances=2, base_rps=3000).snapshots[-1].nodes["app"]
    backlog_wait_s = app.queue_depth / 2000
    assert app.queue_depth == pytest.approx(app.served_rps * backlog_wait_s)  # L = lambda * W
    # Saturated processing (S / (1 - 0.95) = 400 ms) + 1 s of backlog = 1,400 ms.
    assert app.latency_ms == pytest.approx(1400)


def test_latency_recovers_once_the_queue_drains():
    spikes = [{"at_s": 2, "duration_s": 2, "multiplier": 2}]
    snaps = app_after_run(app_instances=1, base_rps=800, spikes=spikes).snapshots
    assert snaps[39].nodes["app"].latency_ms > 1000  # full queue at the end of the spike
    assert snaps[95].nodes["app"].latency_ms == pytest.approx(100)  # back to rho = 0.8


def test_client_adds_no_latency(graph):
    snap = Simulator(graph, make_scenario(base_rps=1000)).step()
    assert snap.nodes["client"].latency_ms == 0
