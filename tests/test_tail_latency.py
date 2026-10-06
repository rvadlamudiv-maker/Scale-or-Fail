import pytest
from pydantic import ValidationError

from engine.models import Edge, SystemGraph
from engine.simulator import Simulator
from tests.conftest import make_scenario


def fanout(n: int, parallel: bool, **shard_fields) -> SystemGraph:
    # Client -> search (10 instances) -> shards, n calls per request.
    return SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "search", "type": "app_server", "instances": 10},
            {"id": "shard", "type": "app_server", "instances": 10 * n, **shard_fields},
        ],
        "edges": [
            {"source": "client", "target": "search"},
            {"source": "search", "target": "shard", "calls_per_request": n, "parallel": parallel},
        ],
    })


def last(graph, base_rps=1000):
    return Simulator(graph, make_scenario(base_rps)).run().snapshots[-1]


def test_parallel_calls_need_a_whole_number_of_calls():
    with pytest.raises(ValidationError, match="whole number"):
        Edge(source="a", target="b", calls_per_request=1.5, parallel=True)


@pytest.mark.parametrize("n, factor", [(1, 1), (2, 1.5), (4, 25 / 12), (10, 2.9289682539682538)])
def test_parallel_fanout_waits_for_the_slowest_of_n(n, factor):
    # Expected max of n exponential response times = mean * H_n.
    edge = Edge(source="a", target="b", calls_per_request=n, parallel=True)
    assert Simulator._call_latency_ms(edge, 10) == pytest.approx(10 * factor)


def test_sequential_calls_add_up():
    edge = Edge(source="a", target="b", calls_per_request=4)
    assert Simulator._call_latency_ms(edge, 10) == pytest.approx(40)


def test_end_to_end_uses_the_fanout_formula():
    snap = last(fanout(10, parallel=True))
    n = snap.nodes
    harmonic = sum(1 / k for k in range(1, 11))
    assert snap.end_to_end_ms == pytest.approx(n["search"].latency_ms + harmonic * n["shard"].latency_ms)


def test_parallel_beats_sequential_but_amplification_grows_with_fanout():
    parallel = [last(fanout(n, parallel=True)).end_to_end_ms for n in (1, 5, 20, 50)]
    sequential = [last(fanout(n, parallel=False)).end_to_end_ms for n in (1, 5, 20, 50)]
    assert all(p <= s for p, s in zip(parallel, sequential))
    assert parallel == sorted(parallel)  # more shards per query, slower queries


def test_fanout_amplifies_failures_too():
    # Each shard call fails 10% of the time; a query needs all 10 to succeed: 0.9^10 = 35%.
    graph = SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "shard", "type": "app_server", "capacity_rps": 900, "max_queue": 0},
        ],
        "edges": [{"source": "client", "target": "shard", "calls_per_request": 10, "parallel": True}],
    })
    assert last(graph, base_rps=100).success_ratio == pytest.approx(0.9**10)
