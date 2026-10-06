import pytest

from engine.models import SystemGraph
from engine.scenario import Scenario
from engine.scoring import correctness_points, score
from engine.simulator import Simulator, reads_served_rps


def with_replica(reads=0.8, cache=False) -> SystemGraph:
    # Client -> app (10 instances) -> primary db (0.2 writes) + one replica (reads), optional cache.
    components = [
        {"id": "client", "type": "client"},
        {"id": "app", "type": "app_server", "instances": 10},
        {"id": "db", "type": "database"},
        {"id": "replica", "type": "replica", "replica_of": "db"},
    ]
    edges = [
        {"source": "client", "target": "app"},
        {"source": "app", "target": "db", "calls_per_request": 0.2},
    ]
    if cache:
        components.append({"id": "cache", "type": "cache", "working_set": 1000})
        edges += [
            {"source": "app", "target": "cache", "calls_per_request": reads},
            {"source": "cache", "target": "replica"},
        ]
    else:
        edges.append({"source": "app", "target": "replica", "calls_per_request": reads})
    return SystemGraph.model_validate({"components": components, "edges": edges})


def run(graph, base_rps, tolerance_ms=100):
    scenario = Scenario.model_validate({
        "name": "fresh", "duration_s": 10, "traffic": {"base_rps": base_rps},
        "goals": {"staleness_tolerance_ms": tolerance_ms},
    })
    return Simulator(graph, scenario).run()


def test_a_healthy_replica_serves_fresh_data():
    result = run(with_replica(), base_rps=1000)  # replica lag stays at 10 ms
    assert all(s.nodes["replica"].stale_rps == 0 for s in result.snapshots)
    assert result.freshness == pytest.approx(1)


def test_stale_share_grows_with_lag():
    # 8,000 rps overloads the replica; its lag climbs toward 1 s.
    replica = run(with_replica(), base_rps=8000).snapshots[-1].nodes["replica"]
    reads = reads_served_rps(replica)
    assert replica.replication_lag_ms > 900
    assert replica.stale_rps == pytest.approx(reads * (1 - 100 / replica.replication_lag_ms))


def test_a_request_is_fresh_only_if_all_its_reads_are():
    snap = run(with_replica(reads=0.8), base_rps=8000).snapshots[-1]
    replica = snap.nodes["replica"]
    fresh_read = 1 - replica.stale_rps / reads_served_rps(replica)
    assert snap.fresh_ratio == pytest.approx(fresh_read**0.8)


def test_a_looser_tolerance_means_fewer_stale_reads():
    strict = run(with_replica(), base_rps=8000, tolerance_ms=50).freshness
    loose = run(with_replica(), base_rps=8000, tolerance_ms=500).freshness
    assert loose > strict


def test_cache_hits_shield_users_from_a_stale_replica():
    snap = run(with_replica(cache=True), base_rps=8000).snapshots[-1]
    hit = snap.nodes["cache"].hit_ratio
    assert snap.fresh_ratio >= hit  # every cache hit was answered without the replica


@pytest.mark.parametrize("freshness, points", [(0.999, 0), (0.989, -600), (0.95, -2940), (0.5, -3000)])
def test_correctness_points(freshness, points):
    assert correctness_points(freshness, 0.999) == points


def test_stale_data_shows_up_on_the_scorecard():
    lines = {line.label: line.points for line in score(run(with_replica(), base_rps=8000)).lines}
    assert lines["Correctness"] < 0
