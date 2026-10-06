import pytest

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_scenario


def pooled_app(pool_size=None, retries=0) -> SystemGraph:
    # Client -> app (1 instance: 1,000 rps, 20 ms service time) through a connection pool.
    edge = {"source": "client", "target": "app", "retries": retries}
    if pool_size is not None:
        edge["pool_size"] = pool_size
    return SystemGraph.model_validate({
        "components": [{"id": "client", "type": "client"}, {"id": "app", "type": "app_server"}],
        "edges": [edge],
    })


def last_app_tick(graph, base_rps=900):
    return Simulator(graph, make_scenario(base_rps)).run().snapshots[-1].nodes["app"]


def test_no_pool_means_no_rejections():
    assert last_app_tick(pooled_app()).pool_rejected_rps == 0


def test_a_big_enough_pool_changes_nothing():
    # At 900 rps the app takes 200 ms (M/M/1), so 900 * 0.2 = 180 calls are in flight.
    app = last_app_tick(pooled_app(pool_size=1000))
    assert app.pool_rejected_rps == 0
    assert app.inbound_rps == pytest.approx(900)


def test_pool_throughput_obeys_littles_law():
    # 10 connections: the rate r settles where r * latency(r) = 10.
    # r * 0.02 / (1 - r/1000) = 10  ->  r = 333.3 rps, latency = 30 ms.
    app = last_app_tick(pooled_app(pool_size=10))
    assert app.inbound_rps == pytest.approx(1000 / 3, rel=1e-3)
    assert app.pool_rejected_rps == pytest.approx(900 - 1000 / 3, rel=1e-3)
    assert app.inbound_rps * app.latency_ms / 1000 == pytest.approx(10, rel=1e-3)  # L = lambda * W


def test_rejected_calls_are_retried():
    app = last_app_tick(pooled_app(pool_size=10, retries=2))
    assert app.retry_rps > 0


def test_a_pool_protects_the_database_from_overload():
    def db_load(pool_size):
        graph = SystemGraph.model_validate({
            "components": [{"id": "client", "type": "client"}, {"id": "db", "type": "database"}],
            "edges": [{"source": "client", "target": "db", **({"pool_size": pool_size} if pool_size else {})}],
        })
        return max(s.nodes["db"].load for s in Simulator(graph, make_scenario(8000)).run().snapshots)

    assert db_load(None) > 1.5  # 8,000 rps into a 5,000 rps database
    assert db_load(50) < 1  # the pool only lets through what fits


def test_every_call_is_either_delivered_or_rejected():
    graph = SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", "instances": 10},
            {"id": "db", "type": "database"},
        ],
        "edges": [
            {"source": "client", "target": "app"},
            {"source": "app", "target": "db", "calls_per_request": 2, "pool_size": 50},
        ],
    })
    for snap in Simulator(graph, make_scenario(4000, noise=0.2)).run().snapshots:
        app, db = snap.nodes["app"], snap.nodes["db"]
        assert app.served_rps * 2 == pytest.approx(db.inbound_rps + db.pool_rejected_rps)
