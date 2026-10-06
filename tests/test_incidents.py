"""Every real-outage scenario ships with a starter design that fails and a solution that survives."""

from pathlib import Path

import pytest

from engine.loader import load_design, load_scenario
from engine.scoring import score
from engine.simulator import Simulator

INCIDENTS = sorted(p for p in (Path(__file__).resolve().parent.parent / "incidents").iterdir() if p.is_dir())
GRADE_ORDER = "FDCBAS"


def run(folder: Path, design: str):
    return Simulator(load_design(folder / f"{design}.yaml"), load_scenario(folder / "scenario.yaml")).run()


@pytest.mark.parametrize("folder", INCIDENTS, ids=lambda p: p.name)
def test_incident_has_its_story_and_sources(folder):
    incident = load_scenario(folder / "scenario.yaml").incident
    assert incident is not None
    assert incident.postmortem_url.startswith("https://")
    assert incident.summary and incident.real_fixes


@pytest.mark.parametrize("folder", INCIDENTS, ids=lambda p: p.name)
def test_starter_fails_and_solution_survives(folder):
    starter, solution = score(run(folder, "starter")), score(run(folder, "solution"))
    assert GRADE_ORDER.index(starter.grade) <= GRADE_ORDER.index("D")
    assert GRADE_ORDER.index(solution.grade) >= GRADE_ORDER.index("A")


def test_the_retry_storm_outlives_its_trigger():
    folder = Path(__file__).resolve().parent.parent / "incidents" / "retry_storm"
    starter, solution = run(folder, "starter"), run(folder, "solution")
    # The surge ends at 20 s. The starter design is still at ~0% success 40 s later...
    assert starter.snapshots[-1].success_ratio < 0.01
    # ...while the solution never goes down at all.
    assert min(s.success_ratio for s in solution.snapshots) > 0.99
