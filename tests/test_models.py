import pytest
from pydantic import ValidationError

from engine.models import SystemGraph

CLIENT = {"id": "client", "type": "client"}
APP = {"id": "app", "type": "app_server"}
DB = {"id": "db", "type": "database"}


def _graph(components, edges):
    return SystemGraph.model_validate({"components": components, "edges": edges})


def test_valid_graph_orders_client_first(graph):
    order = graph.topological_order()
    assert order[0] == "client"
    assert order.index("lb") < order.index("app") < order.index("db")


def test_capacity_scales_with_instances(graph):
    assert graph.component("app").total_capacity_rps == 4_000


@pytest.mark.parametrize(
    "components, edges, message",
    [
        ([APP, DB], [{"source": "app", "target": "db"}], "exactly one client"),
        ([CLIENT, APP], [{"source": "client", "target": "nope"}], "unknown component"),
        ([CLIENT, APP], [], "not connected"),
        ([CLIENT, APP, APP], [{"source": "client", "target": "app"}], "duplicate component"),
        ([CLIENT, APP], [{"source": "app", "target": "app"}], "self-loop"),
        ([CLIENT, APP], [{"source": "app", "target": "client"}], "into the client"),
        (
            [CLIENT, APP, DB],
            [
                {"source": "client", "target": "app"},
                {"source": "app", "target": "db"},
                {"source": "db", "target": "app"},
            ],
            "cycle",
        ),
    ],
)
def test_invalid_graphs_are_rejected(components, edges, message):
    with pytest.raises(ValidationError, match=message):
        _graph(components, edges)
