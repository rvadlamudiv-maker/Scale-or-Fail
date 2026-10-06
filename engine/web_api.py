"""The engine's entry point for the browser (run through Pyodide).

Takes a design and a scenario as YAML text, runs the simulation, and returns everything
the game screen needs as one JSON string: the score, headline metrics, chaos events and
a per-tick timeline for the visualization.
"""

from __future__ import annotations

import json

import yaml
from pydantic import ValidationError

from engine.models import SystemGraph
from engine.scenario import Scenario
from engine.scoring import score
from engine.simulator import Simulator


def run(design_yaml: str, scenario_yaml: str) -> str:
    try:
        design = SystemGraph.model_validate(yaml.safe_load(design_yaml))
        scenario = Scenario.model_validate(yaml.safe_load(scenario_yaml))
        result = Simulator(design, scenario).run()
    except (ValidationError, ValueError, yaml.YAMLError) as exc:
        return json.dumps({"ok": False, "error": str(exc)})

    card = score(result)
    payload = {
        "ok": True,
        "scenario": scenario.name,
        "score": {
            "total": card.total,
            "grade": card.grade,
            "lines": [{"label": l.label, "detail": l.detail, "points": l.points} for l in card.lines],
        },
        "metrics": {
            "availability": result.availability,
            "p50_ms": result.latency_percentile(50),
            "p99_ms": result.latency_percentile(99),
            "cost_per_hour": result.avg_cost_per_hour,
            "freshness": result.freshness,
            "diverged_writes": result.diverged_writes,
        },
        "events": [{"t": s.t, "label": label} for s in result.snapshots for label in s.events],
        "ticks": [
            {
                "t": round(s.t, 2),
                "ok": round(s.success_ratio, 4),
                "e2e_ms": round(s.end_to_end_ms, 1),
                "nodes": {
                    node_id: {
                        "load": round(n.load, 3),
                        "served": round(n.served_rps),
                        "failed": round(n.dropped_rps + n.timed_out_rps + n.pool_rejected_rps + n.wasted_rps),
                        "latency_ms": round(n.latency_ms, 1),
                        "queue": round(n.queue_depth),
                        "instances": n.instances,
                    }
                    for node_id, n in s.nodes.items()
                },
            }
            for s in result.snapshots
        ],
    }
    return json.dumps(payload)
