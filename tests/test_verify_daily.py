"""The nightly leaderboard check re-runs designs exactly the way the browser did."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from verify_daily import check, scenario_for_daily  # noqa: E402

from engine.web_api import run


def test_daily_rotation_matches_the_web_app():
    assert scenario_for_daily(1)[0] == "43_seconds"
    assert scenario_for_daily(9)[0] == "monday_after_holidays"
    assert "seed: 9" in scenario_for_daily(9)[1]
    # Adding an incident never changes past dailies: the new rotation starts at #11.
    assert scenario_for_daily(10)[0] == "retry_storm"
    assert scenario_for_daily(11)[0] == "ticket_rush"
    assert scenario_for_daily(12)[0] == "43_seconds"
    assert scenario_for_daily(17)[0] == "ticket_rush"


def _honest_row(daily: int, design: str) -> dict:
    out = json.loads(run(design, scenario_for_daily(daily)[1]))
    return {"daily": daily, "grade": out["score"]["grade"], "total": out["score"]["total"], "design_yaml": design}


def test_honest_score_is_verified():
    design = (ROOT / "incidents/monday_after_holidays/solution.yaml").read_text()
    assert check(_honest_row(9, design))[0]


def test_inflated_score_is_hidden():
    design = (ROOT / "incidents/monday_after_holidays/starter.yaml").read_text()
    row = _honest_row(9, design) | {"grade": "S", "total": 10_000}
    ok, reason = check(row)
    assert not ok and "engine says" in reason


def test_missing_or_broken_design_is_hidden():
    assert not check({"daily": 9, "grade": "S", "total": 10_000, "design_yaml": ""})[0]
    assert not check({"daily": 9, "grade": "S", "total": 10_000, "design_yaml": "nodes: [oops"})[0]
