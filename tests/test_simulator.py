import pytest

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_graph, make_scenario


def test_tick_count_matches_duration(graph):
    assert len(Simulator(graph, make_scenario()).run().snapshots) == 100


def test_under_capacity_nothing_is_dropped_or_queued(graph):
    for node in Simulator(graph, make_scenario(base_rps=1000)).run().summary().values():
        assert node.drop_rate == 0
        assert node.peak_queue == 0


def test_requests_are_conserved_with_queues(graph):
    sim = Simulator(graph, make_scenario(base_rps=9000, noise=0.2))
    prev_queue = {node_id: 0.0 for node_id in graph.topological_order()}
    for snap in sim.iter_ticks():
        for node_id, tick in snap.nodes.items():
            arrived = prev_queue[node_id] + tick.inbound_rps * sim.dt
            left = (tick.served_rps + tick.dropped_rps) * sim.dt + tick.queue_depth
            assert arrived == pytest.approx(left)
            prev_queue[node_id] = tick.queue_depth


def test_overload_fills_the_queue_before_dropping():
    # App: 2 instances = 2,000 rps capacity and a 2,000-request queue. Traffic: 3,000 rps.
    snaps = Simulator(make_graph(app_instances=2), make_scenario(base_rps=3000)).run().snapshots
    first, last = snaps[0].nodes["app"], snaps[-1].nodes["app"]
    assert first.served_rps == pytest.approx(2000)
    assert first.queue_depth == pytest.approx(100)  # 1,000 rps excess * 0.1 s
    assert first.dropped_rps == 0
    assert last.queue_depth == pytest.approx(2000)  # queue is full...
    assert last.dropped_rps == pytest.approx(1000)  # ...so the excess is dropped
    assert snaps[-1].nodes["db"].inbound_rps == pytest.approx(2000)


def test_queue_drains_after_the_spike():
    # App: 1,000 rps. Traffic 800 rps, doubled to 1,600 rps from t=2s to t=4s.
    scenario = make_scenario(base_rps=800, spikes=[{"at_s": 2, "duration_s": 2, "multiplier": 2}])
    snaps = Simulator(make_graph(app_instances=1), scenario).run().snapshots
    assert snaps[39].nodes["app"].queue_depth == pytest.approx(1000)  # full at the end of the spike
    assert snaps[40].nodes["app"].served_rps == pytest.approx(1000)  # still busy after it ends
    assert snaps[95].nodes["app"].queue_depth == pytest.approx(0)  # drained ~5 s later


def test_fanout_multiplies_downstream_calls():
    snap = Simulator(make_graph(db_calls=1.5), make_scenario(base_rps=1000)).step()
    assert snap.nodes["db"].inbound_rps == pytest.approx(1500)


def test_load_balancer_splits_by_weight():
    graph = SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "lb", "type": "load_balancer"},
            {"id": "a", "type": "app_server"},
            {"id": "b", "type": "app_server"},
        ],
        "edges": [
            {"source": "client", "target": "lb"},
            {"source": "lb", "target": "a", "weight": 3},
            {"source": "lb", "target": "b", "weight": 1},
        ],
    })
    snap = Simulator(graph, make_scenario(base_rps=800)).step()
    assert snap.nodes["a"].inbound_rps == pytest.approx(600)
    assert snap.nodes["b"].inbound_rps == pytest.approx(200)


def test_spike_only_while_active(graph):
    scenario = make_scenario(base_rps=1000, spikes=[{"at_s": 2, "duration_s": 3, "multiplier": 4}])
    by_time = {round(s.t, 1): s.nodes["client"].inbound_rps for s in Simulator(graph, scenario).run().snapshots}
    assert by_time[1.9] == 1000
    assert by_time[2.0] == 4000
    assert by_time[4.9] == 4000
    assert by_time[5.0] == 1000


def test_same_seed_is_deterministic(graph):
    scenario = make_scenario(base_rps=5000, noise=0.3)
    assert Simulator(graph, scenario).run().snapshots == Simulator(graph, scenario).run().snapshots


def test_different_seeds_differ_when_noisy(graph):
    scenario = make_scenario(base_rps=5000, noise=0.3)
    a = Simulator(graph, scenario, seed=1).run().snapshots
    b = Simulator(graph, scenario, seed=2).run().snapshots
    assert a != b
