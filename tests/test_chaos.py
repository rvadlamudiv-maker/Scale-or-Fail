import pytest

from engine.models import SystemGraph
from engine.scenario import Scenario
from engine.simulator import Simulator


def app_graph(**app_fields) -> SystemGraph:
    # Client -> app (4 instances = 4,000 rps, 20 ms service time).
    return SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", "instances": 4, **app_fields},
        ],
        "edges": [{"source": "client", "target": "app"}],
    })


def chaos(*events, base_rps=1000) -> Scenario:
    return Scenario.model_validate({
        "name": "chaos", "duration_s": 10, "traffic": {"base_rps": base_rps}, "events": list(events),
    })


def app_ticks(graph, scenario):
    return [s.nodes["app"] for s in Simulator(graph, scenario).run().snapshots]


def test_events_for_missing_components_are_skipped():
    snaps = Simulator(app_graph(), chaos({"at_s": 1, "kind": "cache_flush", "target": "cache"})).run().snapshots
    assert snaps[0].events == ("skipped: cache flushed (no 'cache' in this design)",)
    assert all(s.success_ratio == 1 for s in snaps)


def test_only_caches_can_be_flushed():
    with pytest.raises(ValueError, match="needs a cache"):
        Simulator(app_graph(), chaos({"at_s": 1, "kind": "cache_flush", "target": "app"}))


def test_killed_instances_stop_serving_and_come_back():
    event = {"at_s": 2, "kind": "kill_instances", "target": "app", "count": 3, "duration_s": 3}
    ticks = app_ticks(app_graph(), chaos(event))
    assert ticks[19].instances == 4
    assert ticks[20].instances == 1  # 3 of 4 killed at 2 s
    assert ticks[49].instances == 1
    assert ticks[50].instances == 4  # back at 5 s


def test_killing_every_instance_fails_everything():
    event = {"at_s": 2, "kind": "kill_instances", "target": "app", "count": 4, "duration_s": 3}
    result = Simulator(app_graph(), chaos(event)).run()
    down = result.snapshots[30]
    assert down.nodes["app"].served_rps == 0
    assert down.success_ratio == 0
    assert result.snapshots[-1].success_ratio == 1  # recovered


def test_the_autoscaler_replaces_dead_instances():
    event = {"at_s": 2, "kind": "kill_instances", "target": "app", "count": 3}  # permanent
    ticks = app_ticks(app_graph(max_instances=8, warmup_s=1), chaos(event))
    assert ticks[20].instances == 1
    assert ticks[31].instances == 4  # back to the minimum after a 1 s boot


def test_a_slowed_down_component_is_slower_and_serves_less():
    event = {"at_s": 2, "kind": "slow_down", "target": "app", "factor": 4, "duration_s": 3}
    ticks = app_ticks(app_graph(), chaos(event, base_rps=500))
    # Normal: 500 / 4,000 = 12.5% busy -> 20 ms / 0.875 = 22.9 ms.
    assert ticks[19].latency_ms == pytest.approx(20 / 0.875)
    # 4x slower: 80 ms service, 1,000 rps capacity -> 50% busy -> 80 / 0.5 = 160 ms.
    assert ticks[30].latency_ms == pytest.approx(160)
    assert ticks[-1].latency_ms == pytest.approx(20 / 0.875)  # recovered


def test_a_flushed_cache_starts_cold_again():
    graph = SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "cache", "type": "cache", "working_set": 1000},
            {"id": "db", "type": "database"},
        ],
        "edges": [{"source": "client", "target": "cache"}, {"source": "cache", "target": "db"}],
    })
    snaps = Simulator(graph, chaos({"at_s": 5, "kind": "cache_flush", "target": "cache"})).run().snapshots
    hits = [s.nodes["cache"].hit_ratio for s in snaps]
    assert hits[49] > 0.8
    assert hits[50] < 0.15  # wiped at 5 s...
    assert hits[-1] > hits[55] > hits[50]  # ...and warming back up


def test_events_are_reported_when_they_start_and_end():
    event = {"at_s": 2, "kind": "slow_down", "target": "app", "factor": 3, "duration_s": 1}
    snaps = Simulator(app_graph(), chaos(event)).run().snapshots
    assert snaps[20].events == ("app 3x slower for 1s",)
    assert snaps[30].events == ("recovered: app 3x slower for 1s",)
    assert sum(len(s.events) for s in snaps) == 2
