import pytest

from engine.models import SystemGraph
from engine.scenario import Scenario


def make_graph(app_instances: int = 4, db_calls: float = 1.0) -> SystemGraph:
    return SystemGraph.model_validate({
        "components": [
            {"id": "client", "type": "client"},
            {"id": "lb", "type": "load_balancer"},
            {"id": "app", "type": "app_server", "instances": app_instances},
            {"id": "db", "type": "database"},
        ],
        "edges": [
            {"source": "client", "target": "lb"},
            {"source": "lb", "target": "app"},
            {"source": "app", "target": "db", "calls_per_request": db_calls},
        ],
    })


def make_scenario(base_rps: float = 1000, noise: float = 0.0, spikes=None) -> Scenario:
    return Scenario.model_validate({
        "name": "test",
        "duration_s": 10,
        "tick_hz": 10,
        "traffic": {"base_rps": base_rps, "noise": noise, "spikes": spikes or []},
    })


@pytest.fixture
def graph() -> SystemGraph:
    return make_graph()
