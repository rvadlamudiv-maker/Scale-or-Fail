import pytest

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_scenario


def test_cost_is_instances_times_price(graph):
    # make_graph: LB $40 + 4 apps x $90 + DB $380 = $780/hr, and the client is free.
    snap = Simulator(graph, make_scenario()).step()
    assert snap.cost_per_hour == pytest.approx(40 + 4 * 90 + 380)
    assert snap.nodes["client"].cost_per_hour == 0
    assert snap.nodes["app"].cost_per_hour == pytest.approx(360)


def test_price_can_be_overridden():
    graph = SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", "instances": 3, "price_per_hour": 10},
        ],
        "edges": [{"source": "client", "target": "app"}],
    })
    assert Simulator(graph, make_scenario()).step().cost_per_hour == pytest.approx(30)


def test_booting_instances_cost_money_too():
    graph = SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", "max_instances": 10,
             "target_utilization": 0.5, "warmup_s": 5},
        ],
        "edges": [{"source": "client", "target": "app"}],
    })
    snaps = Simulator(graph, make_scenario(base_rps=2000)).run().snapshots
    # Tick 1: 1 serving + 3 booting, all billed.
    assert snaps[1].nodes["app"].instances == 1
    assert snaps[1].cost_per_hour == pytest.approx(4 * 90)


def test_fixed_designs_have_a_flat_cost(graph):
    result = Simulator(graph, make_scenario(base_rps=9000)).run()
    assert result.avg_cost_per_hour == pytest.approx(result.peak_cost_per_hour)


def test_scaling_out_raises_the_bill():
    graph = SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", "instances": 4, "max_instances": 12, "warmup_s": 0},
        ],
        "edges": [{"source": "client", "target": "app"}],
    })
    result = Simulator(graph, make_scenario(base_rps=6000)).run()
    assert result.snapshots[0].cost_per_hour == pytest.approx(4 * 90)  # starts with 4 instances
    assert result.peak_cost_per_hour == pytest.approx(9 * 90)  # ceil(6000 / (1000 * 0.7)) = 9


def test_dead_instances_do_not_lower_the_bill():
    # Killing 3 of 4 servers must not make the design cheaper: you pay for the fleet you provisioned.
    from engine.scenario import Scenario

    graph = SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", "instances": 4},
        ],
        "edges": [{"source": "client", "target": "app"}],
    })
    scenario = Scenario.model_validate({
        "name": "kill", "duration_s": 5, "traffic": {"base_rps": 1000},
        "events": [{"at_s": 1, "kind": "kill_instances", "target": "app", "count": 3}],
    })
    result = Simulator(graph, scenario).run()
    assert result.snapshots[-1].nodes["app"].instances == 1
    assert result.snapshots[-1].cost_per_hour == pytest.approx(4 * 90)
