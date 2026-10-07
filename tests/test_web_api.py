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
    assert out["client_id"] == "client"
    assert out["goals"] == {"availability": 0.999, "p99_ms": 500}


def test_reports_chaos_events():
    out = json.loads(run(read("incidents/bad_regex/starter.yaml"), read("incidents/bad_regex/scenario.yaml")))
    assert [e["t"] for e in out["events"]] == [10.0, 35.0]


def test_a_broken_design_returns_an_error_instead_of_crashing():
    broken = "components:\n  - id: app\n    type: app_server\nedges: []\n"  # no client
    out = json.loads(run(broken, read("scenarios/url_shortener.yaml")))
    assert out["ok"] is False
    assert "exactly one client" in out["error"]


def test_incident_scenarios_include_the_real_story():
    out = json.loads(run(read("incidents/retry_storm/starter.yaml"), read("incidents/retry_storm/scenario.yaml")))
    assert out["incident"]["postmortem_url"] == "https://aws.amazon.com/message/12721/"
    assert len(out["incident"]["real_fixes"]) == 4
    practice = json.loads(run(read("designs/solid.yaml"), read("scenarios/url_shortener.yaml")))
    assert practice["incident"] is None


def test_an_unquoted_incident_date_still_loads():
    # YAML reads `date: 2018-10-21` (no quotes) as a date; the engine should accept it as text.
    scenario = read("incidents/43_seconds/scenario.yaml").replace('date: "2018-10-21"', "date: 2018-10-21")
    out = json.loads(run(read("incidents/43_seconds/solution.yaml"), scenario))
    assert out["ok"] is True
    assert out["incident"]["date"] == "2018-10-21"


def test_every_scenario_has_a_hint():
    from engine.loader import load_scenario

    for path in sorted(ROOT.glob("scenarios/*.yaml")) + sorted(ROOT.glob("incidents/*/scenario.yaml")):
        assert load_scenario(path).hint, f"{path} has no hint"
