import pytest

from engine.models import SystemGraph
from engine.scenario import Scenario
from engine.simulator import Simulator

# 1 of 4 app instances becomes 10x slower from t=2s to t=8s, but stays in rotation.
GRAY = {"at_s": 2, "kind": "gray_failure", "target": "app", "count": 1, "factor": 10, "duration_s": 6}


def app_graph(**app_fields) -> SystemGraph:
    # Client -> app (4 instances = 4,000 rps, 20 ms service time).
    return SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", "instances": 4, **app_fields},
        ],
        "edges": [{"source": "client", "target": "app"}],
    })


def run(graph, base_rps=2000):
    scenario = Scenario.model_validate({
        "name": "gray", "duration_s": 10, "traffic": {"base_rps": base_rps}, "events": [GRAY],
    })
    return Simulator(graph, scenario).run().snapshots


def test_round_robin_keeps_feeding_the_slow_instance():
    # It still gets 1/4 of 2,000 rps = 500 rps, but can now only do 1,000 / 10 = 100 rps.
    snap = run(app_graph())[70]
    assert snap.nodes["app"].dropped_rps == pytest.approx(400)
    assert snap.success_ratio == pytest.approx(0.8)  # 400 of 2,000 requests fail


def test_least_outstanding_sends_the_slow_instance_less():
    # Its share drops to 100 / (3,000 + 100) of traffic: about 65 rps, which it can handle.
    snap = run(app_graph(balancing="least_outstanding"))[70]
    assert snap.nodes["app"].dropped_rps == 0
    assert snap.success_ratio == pytest.approx(1)


def test_a_gray_instance_drags_latency_up_even_when_nothing_fails():
    healthy = run(app_graph(balancing="least_outstanding"))[10].nodes["app"].latency_ms
    gray = run(app_graph(balancing="least_outstanding"))[70].nodes["app"].latency_ms
    assert gray > healthy


def test_the_autoscaler_does_not_replace_a_gray_instance():
    # It still counts as serving, so as far as the autoscaler knows nothing is wrong.
    snaps = run(app_graph(max_instances=10, warmup_s=0), base_rps=1000)
    assert {s.nodes["app"].instances for s in snaps} == {4}


def test_everything_recovers_when_the_instance_does():
    snaps = run(app_graph())
    assert snaps[-1].success_ratio == pytest.approx(1)
    assert snaps[-1].nodes["app"].queue_depth == pytest.approx(0)


def test_gray_failures_are_reported():
    snaps = run(app_graph())
    assert snaps[20].events == ("1 app instance(s) 10x slower, still passing health checks for 6s",)
