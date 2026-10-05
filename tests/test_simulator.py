import pytest

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_graph, make_scenario


def test_tick_count_matches_duration(graph):
    assert len(Simulator(graph, make_scenario()).run().snapshots) == 100


def test_under_capacity_nothing_is_dropped(graph):
    for node in Simulator(graph, make_scenario(base_rps=1000)).run().summary().values():
        assert node.drop_rate == 0


def test_flow_is_conserved_at_every_node(graph):
    for snap in Simulator(graph, make_scenario(base_rps=9000, noise=0.2)).run().snapshots:
        for tick in snap.nodes.values():
            assert tick.inbound_rps == pytest.approx(tick.served_rps + tick.dropped_rps)


def test_overload_drops_excess_at_the_bottleneck():
    snap = Simulator(make_graph(app_instances=2), make_scenario(base_rps=3000)).step()
    assert snap.nodes["app"].served_rps == 2000
    assert snap.nodes["app"].dropped_rps == 1000
    assert snap.nodes["app"].load == pytest.approx(1.5)
    assert snap.nodes["db"].inbound_rps == 2000


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
