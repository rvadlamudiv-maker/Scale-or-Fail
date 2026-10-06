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


def test_monday_preemptive_scaling_beats_faster_autoscaling():
    import yaml

    from engine.models import SystemGraph

    folder = Path(__file__).resolve().parent.parent / "incidents" / "monday_after_holidays"
    scenario = load_scenario(folder / "scenario.yaml")
    faster = yaml.safe_load(open(folder / "starter.yaml"))
    next(c for c in faster["components"] if c["id"] == "network_hub")["warmup_s"] = 5
    fast_autoscaling = Simulator(SystemGraph.model_validate(faster), scenario).run()
    prescaled = run(folder, "solution")
    # Even a 5 s scale-up leaves a gap when traffic triples at once; scaling ahead of time leaves none.
    assert min(s.success_ratio for s in fast_autoscaling.snapshots) < 0.9
    assert min(s.success_ratio for s in prescaled.snapshots) > 0.99


def test_a_canary_limits_the_blast_radius_of_a_bad_deploy():
    import yaml

    from engine.models import SystemGraph

    folder = Path(__file__).resolve().parent.parent / "incidents" / "bad_regex"
    scenario = load_scenario(folder / "scenario.yaml")
    canary_only = yaml.safe_load(open(folder / "starter.yaml"))
    next(c for c in canary_only["components"] if c["id"] == "edge")["rollout"] = "canary"
    global_rollout = run(folder, "starter")
    canary = Simulator(SystemGraph.model_validate(canary_only), scenario).run()
    # Global: almost every request fails until the rollback. Canary: only the canary's share does.
    assert min(s.success_ratio for s in global_rollout.snapshots) < 0.1
    assert min(s.success_ratio for s in canary.snapshots) > 0.85


def test_you_cannot_buy_your_way_out_of_a_split_brain():
    import yaml

    from engine.models import SystemGraph
    from engine.scoring import score as score_run

    folder = Path(__file__).resolve().parent.parent / "incidents" / "43_seconds"
    scenario = load_scenario(folder / "scenario.yaml")
    brute_force = yaml.safe_load(open(folder / "starter.yaml"))
    next(c for c in brute_force["components"] if c["id"] == "app")["instances"] = 200
    result = Simulator(SystemGraph.model_validate(brute_force), scenario).run()
    # 10x the app servers absorbs the cross-country latency, but the diverged writes remain.
    assert result.availability > 0.999
    assert result.diverged_writes > 0
    assert score_run(result).grade in "DF"
    assert run(folder, "solution").diverged_writes == 0
