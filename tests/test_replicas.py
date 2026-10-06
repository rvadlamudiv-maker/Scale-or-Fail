import pytest
from pydantic import ValidationError

from engine.models import SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_scenario


def with_replicas(replicas=1, writes=0.2, reads=0.8) -> SystemGraph:
    # Client -> app (10 instances) -> primary db (writes) + replicas (reads).
    return SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", "instances": 10},
            {"id": "db", "type": "database"},
            {"id": "replica", "type": "replica", "replica_of": "db", "instances": replicas},
        ],
        "edges": [
            {"source": "client", "target": "app"},
            {"source": "app", "target": "db", "calls_per_request": writes},
            {"source": "app", "target": "replica", "calls_per_request": reads},
        ],
    })


def last_tick(graph, base_rps=1000):
    return Simulator(graph, make_scenario(base_rps)).run().snapshots[-1].nodes


@pytest.mark.parametrize("replica_of, message", [(None, "must set replica_of"), ("app", "must set replica_of")])
def test_a_replica_must_copy_a_database(replica_of, message):
    with pytest.raises(ValidationError, match=message):
        SystemGraph.model_validate({
            "components": [
                {"id": "client", "type": "client"},
                {"id": "app", "type": "app_server"},
                {"id": "replica", "type": "replica", "replica_of": replica_of},
            ],
            "edges": [{"source": "client", "target": "app"}, {"source": "app", "target": "replica"}],
        })


def test_only_replicas_can_set_replica_of():
    with pytest.raises(ValidationError, match="only replicas"):
        SystemGraph.model_validate({
            "components": [
                {"id": "client", "type": "client"},
                {"id": "db", "type": "database"},
                {"id": "db2", "type": "database", "replica_of": "db"},
            ],
            "edges": [{"source": "client", "target": "db"}, {"source": "client", "target": "db2"}],
        })


def test_primary_is_simulated_before_its_replica():
    order = with_replicas().topological_order()
    assert order.index("db") < order.index("replica")


def test_each_replica_replays_every_write():
    # 1,000 rps: 200 writes/s to the primary, 800 reads/s to the replicas.
    for replicas in (1, 2, 3):
        replica = last_tick(with_replicas(replicas))["replica"]
        assert replica.replication_rps == pytest.approx(200 * replicas)
        assert replica.inbound_rps == pytest.approx(800 + 200 * replicas)


def test_replicas_do_not_reduce_write_load_on_the_primary():
    loads = [last_tick(with_replicas(n))["db"].inbound_rps for n in (1, 2, 3)]
    assert loads == pytest.approx([200, 200, 200])


def test_a_healthy_replica_has_only_the_base_lag():
    assert last_tick(with_replicas())["replica"].replication_lag_ms == pytest.approx(10)


def test_an_overloaded_replica_falls_behind():
    # 8,000 rps: 6,400 reads + 1,600 writes = 8,000/s into one 5,000 rps replica.
    snaps = Simulator(with_replicas(), make_scenario(8000)).run().snapshots
    lags = [s.nodes["replica"].replication_lag_ms for s in snaps]
    assert lags[0] < lags[5] < lags[9]  # the backlog keeps growing...
    assert lags[-1] > 900  # ...until the replica is about a second behind
