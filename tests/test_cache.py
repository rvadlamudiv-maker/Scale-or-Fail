import pytest

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_scenario


def cached_db(db_capacity=5000, **cache_fields) -> SystemGraph:
    # Client -> cache -> db
    return SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "cache", "type": "cache", **cache_fields},
            {"id": "db", "type": "database", "capacity_rps": db_capacity},
        ],
        "edges": [{"source": "client", "target": "cache"}, {"source": "cache", "target": "db"}],
    })


def run(graph, base_rps=1000):
    return Simulator(graph, make_scenario(base_rps)).run().snapshots


def test_only_misses_reach_the_database():
    snap = run(cached_db())[-1]
    cache = snap.nodes["cache"]
    assert snap.nodes["db"].inbound_rps == pytest.approx(cache.served_rps * (1 - cache.hit_ratio))


def test_hit_ratio_follows_the_ttl_cache_formula():
    # 1,000 rps over 1,000 keys = 1 request/s per key; TTL 1 s -> x = 1 -> hit = 0.9 * 1/2.
    cache = run(cached_db(working_set=1000, ttl_s=1))[-1].nodes["cache"]
    assert cache.hit_ratio == pytest.approx(0.45)


def test_longer_ttl_means_more_hits():
    hits = [run(cached_db(working_set=1000, ttl_s=ttl))[-1].nodes["cache"].hit_ratio for ttl in (1, 10, 100)]
    assert hits == sorted(hits)
    assert hits[-1] == pytest.approx(0.9, rel=0.02)  # approaches max_hit_ratio


def test_cold_cache_starts_empty_and_warms_up():
    # Warm-up time = working_set / traffic = 1,000 / 1,000 = 1 s.
    ticks = [s.nodes["cache"].hit_ratio for s in run(cached_db(working_set=1000, ttl_s=100, cold_start=True))]
    target = run(cached_db(working_set=1000, ttl_s=100))[-1].nodes["cache"].hit_ratio
    assert ticks[0] < 0.1 * target
    assert ticks == sorted(ticks)  # only ever warms up
    assert ticks[50] == pytest.approx(target, rel=0.01)  # warm after 5 warm-up periods


def test_cold_start_causes_a_thundering_herd():
    # The DB is fine behind a warm cache but overloaded while a cold one fills up.
    warm = run(cached_db(db_capacity=500), base_rps=2000)
    cold = run(cached_db(db_capacity=500, cold_start=True), base_rps=2000)
    assert max(s.nodes["db"].load for s in warm) < 1
    assert cold[0].nodes["db"].load > 3


def test_end_to_end_only_counts_the_database_on_a_miss():
    snap = run(cached_db())[-1]
    n = snap.nodes
    expected = n["cache"].latency_ms + (1 - n["cache"].hit_ratio) * n["db"].latency_ms
    assert snap.end_to_end_ms == pytest.approx(expected)
