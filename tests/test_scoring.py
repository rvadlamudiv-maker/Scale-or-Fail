from pathlib import Path

import pytest

from engine.loader import load_design, load_scenario
from engine.models import Edge, SystemGraph
from engine.scoring import availability_points, cost_points, grade_for, latency_points, score
from engine.simulator import Simulator
from tests.conftest import make_scenario

ROOT = Path(__file__).resolve().parent.parent


def single_app(**edge_fields) -> SystemGraph:
    # Client -> app (1,000 rps, no queue: anything over capacity fails immediately).
    return SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "app", "type": "app_server", "max_queue": 0},
        ],
        "edges": [{"source": "client", "target": "app", **edge_fields}],
    })


def test_healthy_design_has_full_availability(graph):
    assert Simulator(graph, make_scenario(base_rps=1000)).run().availability == pytest.approx(1.0)


def test_availability_is_the_share_of_requests_that_succeed():
    # 1,500 rps into 1,000 rps of capacity: one request in three fails.
    result = Simulator(single_app(), make_scenario(base_rps=1500)).run()
    assert result.availability == pytest.approx(2 / 3)


def test_retries_rescue_failed_calls():
    ok = {"app": 0.5}
    assert Simulator._call_success(Edge(source="client", target="app"), ok) == pytest.approx(0.5)
    assert Simulator._call_success(Edge(source="client", target="app", retries=1), ok) == pytest.approx(0.75)
    assert Simulator._call_success(Edge(source="client", target="app", retries=2), ok) == pytest.approx(0.875)


@pytest.mark.parametrize("availability, points", [(0.999, 0), (0.995, -480), (0.989, -1200), (0.5, -6000)])
def test_availability_points(availability, points):
    assert availability_points(availability, 0.999) == points


@pytest.mark.parametrize("p99, points", [(300, 0), (500, 0), (1000, -400), (2000, -800), (10**9, -3000)])
def test_latency_points_per_doubling(p99, points):
    assert latency_points(p99, 500) == points


@pytest.mark.parametrize("cost, points", [(0, 1000), (750, 500), (1500, 0), (2250, -1500), (9000, -3000)])
def test_cost_points(cost, points):
    assert cost_points(cost, 1500) == points


@pytest.mark.parametrize("total, grade", [(10_160, "S"), (9_500, "A"), (8_000, "B"), (6_500, "C"), (4_500, "D"), (100, "F")])
def test_grades(total, grade):
    assert grade_for(total) == grade


@pytest.mark.parametrize("design, grade", [("starter", "F"), ("cached", "D"), ("solid", "S")])
def test_sample_designs_get_the_expected_grade(design, grade):
    scenario = load_scenario(ROOT / "scenarios/url_shortener.yaml")
    result = Simulator(load_design(ROOT / f"designs/{design}.yaml"), scenario).run()
    assert score(result).grade == grade
