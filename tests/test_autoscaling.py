import pytest
from pydantic import ValidationError

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_scenario


def autoscaled_app(**app_fields) -> SystemGraph:
    # Client -> app (starts with 1 instance = 1,000 rps).
    return SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", **app_fields},
        ],
        "edges": [{"source": "client", "target": "app"}],
    })


def app_ticks(graph, base_rps, spikes=None):
    return [s.nodes["app"] for s in Simulator(graph, make_scenario(base_rps, spikes=spikes)).run().snapshots]


def test_max_instances_cannot_be_below_instances():
    with pytest.raises(ValidationError, match="max_instances must be >= instances"):
        autoscaled_app(instances=4, max_instances=2)


def test_without_max_instances_the_size_is_fixed():
    ticks = app_ticks(autoscaled_app(instances=2), base_rps=5000)
    assert {t.instances for t in ticks} == {2}


def test_scales_out_to_hit_the_target_utilization():
    # 2,000 rps at 50% target utilization of 1,000 rps instances -> 4 instances.
    ticks = app_ticks(autoscaled_app(max_instances=10, target_utilization=0.5, warmup_s=0), base_rps=2000)
    assert ticks[-1].instances == 4
    assert ticks[-1].served_rps == pytest.approx(2000)


def test_new_instances_only_serve_after_warming_up():
    ticks = app_ticks(autoscaled_app(max_instances=10, target_utilization=0.5, warmup_s=2), base_rps=2000)
    assert ticks[19].instances == 1 and ticks[19].booting_instances == 3  # still warming up at 1.9 s
    assert ticks[20].instances == 4 and ticks[20].booting_instances == 0  # ready at 2.0 s


def test_never_exceeds_max_instances():
    ticks = app_ticks(autoscaled_app(max_instances=3, warmup_s=0), base_rps=50_000)
    assert max(t.instances for t in ticks) == 3


def test_scales_back_in_after_load_stays_low():
    spikes = [{"at_s": 0, "duration_s": 2, "multiplier": 4}]  # 2,000 rps for 2 s, then 500 rps
    graph = autoscaled_app(max_instances=10, target_utilization=0.5, warmup_s=0, scale_in_after_s=3)
    ticks = app_ticks(graph, base_rps=500, spikes=spikes)
    assert max(t.instances for t in ticks) == 4
    assert ticks[40].instances == 4  # 2 s after the spike: not long enough yet
    assert ticks[-1].instances == 1  # low for more than 3 s: back to the minimum
