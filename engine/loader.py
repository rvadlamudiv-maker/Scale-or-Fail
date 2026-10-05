"""Load scenarios and designs from YAML files."""

from __future__ import annotations

from pathlib import Path

import yaml

from engine.models import SystemGraph
from engine.scenario import Scenario


def _read_yaml(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the top level")
    return data


def load_scenario(path: str | Path) -> Scenario:
    return Scenario.model_validate(_read_yaml(path))


def load_design(path: str | Path) -> SystemGraph:
    return SystemGraph.model_validate(_read_yaml(path))
