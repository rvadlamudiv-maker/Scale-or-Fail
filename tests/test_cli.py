"""Smoke tests: every sample design runs against every sample scenario."""

from pathlib import Path

import pytest

from engine.cli import main

ROOT = Path(__file__).resolve().parent.parent
DESIGNS = sorted((ROOT / "designs").glob("*.yaml"))
SCENARIOS = sorted((ROOT / "scenarios").glob("*.yaml"))


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda p: p.stem)
@pytest.mark.parametrize("design", DESIGNS, ids=lambda p: p.stem)
def test_every_design_runs_against_every_scenario(design, scenario, capsys):
    assert main(["run", str(scenario), str(design)]) == 0
    assert "End-to-end latency" in capsys.readouterr().out


def test_cli_rejects_a_missing_file(tmp_path):
    assert main(["run", str(tmp_path / "nope.yaml"), str(DESIGNS[0])]) == 2
