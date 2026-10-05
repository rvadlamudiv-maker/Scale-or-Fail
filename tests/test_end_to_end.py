import pytest

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_graph, make_scenario


def test_end_to_end_adds_latency_along_the_path():
    # client -> lb -> app -> db, with 1.5 DB calls per app request.
    snap = Simulator(make_graph(db_calls=1.5), make_scenario(base_rps=1000)).step()
    n = snap.nodes
    expected = n["lb"].latency_ms + n["app"].latency_ms + 1.5 * n["db"].latency_ms
    assert snap.end_to_end_ms == pytest.approx(expected)


def test_load_balancer_averages_its_targets_by_weight():
    graph = SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "lb", "type": "load_balancer"},
            {"id": "fast", "type": "app_server", "service_ms": 10},
            {"id": "slow", "type": "app_server", "service_ms": 50},
        ],
        "edges": [
            {"source": "client", "target": "lb"},
            {"source": "lb", "target": "fast", "weight": 3},
            {"source": "lb", "target": "slow", "weight": 1},
        ],
    })
    snap = Simulator(graph, make_scenario(base_rps=800)).step()
    n = snap.nodes
    expected = n["lb"].latency_ms + 0.75 * n["fast"].latency_ms + 0.25 * n["slow"].latency_ms
    assert snap.end_to_end_ms == pytest.approx(expected)


def test_steady_traffic_has_equal_p50_and_p99(graph):
    result = Simulator(graph, make_scenario(base_rps=1000)).run()
    assert result.latency_percentile(50) == pytest.approx(result.latency_percentile(99))


def test_a_spike_pushes_p99_above_p50():
    spikes = [{"at_s": 8, "duration_s": 1, "multiplier": 3}]
    result = Simulator(make_graph(app_instances=1), make_scenario(base_rps=800, spikes=spikes)).run()
    p50, p99 = result.latency_percentile(50), result.latency_percentile(99)
    assert p99 > 3 * p50
