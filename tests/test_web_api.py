import json
from pathlib import Path

from engine.web_api import run

ROOT = Path(__file__).resolve().parent.parent


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_runs_a_design_and_returns_the_score_and_timeline():
    out = json.loads(run(read("designs/solid.yaml"), read("scenarios/url_shortener.yaml")))
    assert out["ok"] is True
    assert out["score"]["grade"] == "S"
    assert out["metrics"]["availability"] > 0.999
    assert len(out["ticks"]) == 600  # 60 s at 10 ticks per second
    assert set(out["ticks"][0]["nodes"]) == {"client", "lb", "app", "cache", "db"}


def test_reports_chaos_events():
    out = json.loads(run(read("incidents/bad_regex/starter.yaml"), read("incidents/bad_regex/scenario.yaml")))
    assert [e["t"] for e in out["events"]] == [10.0, 35.0]


def test_a_broken_design_returns_an_error_instead_of_crashing():
    broken = "components:\n  - id: app\n    type: app_server\nedges: []\n"  # no client
    out = json.loads(run(broken, read("scenarios/url_shortener.yaml")))
    assert out["ok"] is False
    assert "exactly one client" in out["error"]
