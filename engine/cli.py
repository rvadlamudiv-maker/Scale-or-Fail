"""Command line runner: python -m engine.cli run SCENARIO DESIGN"""

from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from engine.loader import load_design, load_scenario
from engine.simulator import SimulationResult, Simulator

console = Console()


def _style_for_load(load: float) -> str:
    if load > 1.0:
        return "bold red"
    if load > 0.8:
        return "yellow"
    return "green"


def _fmt(rps: float) -> str:
    return f"{rps:,.0f}"


def print_timeline(result: SimulationResult, every_s: float) -> None:
    node_ids = list(result.snapshots[0].nodes)
    table = Table(title="Served RPS over time (green ok / yellow >80% / red overloaded)")
    table.add_column("t (s)", justify="right")
    for node_id in node_ids:
        table.add_column(node_id, justify="right")
    step = max(1, round(every_s * result.scenario.tick_hz))
    for snap in result.snapshots[::step]:
        cells = []
        for node_id in node_ids:
            tick = snap.nodes[node_id]
            text = _fmt(tick.served_rps)
            if tick.dropped_rps > 0:
                text += f" (-{_fmt(tick.dropped_rps)})"
            cells.append(f"[{_style_for_load(tick.load)}]{text}[/]")
        table.add_row(f"{snap.t:.1f}", *cells)
    console.print(table)


def print_summary(result: SimulationResult) -> None:
    table = Table(title="Summary")
    for col in ("node", "avg in", "avg served", "peak served", "peak load", "dropped", "overloaded"):
        table.add_column(col, justify="left" if col == "node" else "right")
    for node_id, s in result.summary().items():
        table.add_row(
            node_id,
            _fmt(s.avg_inbound_rps),
            _fmt(s.avg_served_rps),
            _fmt(s.peak_served_rps),
            f"[{_style_for_load(s.peak_load)}]{s.peak_load:.0%}[/]",
            f"{s.drop_rate:.1%}",
            f"{s.overloaded_s:.1f}s",
        )
    console.print(table)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sof", description="Scale or Fail simulation engine")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a design against a scenario")
    run.add_argument("scenario", help="path to scenario YAML")
    run.add_argument("design", help="path to design YAML")
    run.add_argument("--every", type=float, default=5.0, help="timeline sample interval (s)")
    run.add_argument("--seed", type=int, default=None, help="override the scenario seed")
    args = parser.parse_args(argv)

    try:
        scenario = load_scenario(args.scenario)
        design = load_design(args.design)
    except (OSError, ValueError, ValidationError) as exc:
        console.print(f"[bold red]Invalid input:[/] {exc}")
        return 2

    console.print(f"[bold]Scenario:[/] {scenario.name}  [dim]{scenario.description}[/]")
    result = Simulator(design, scenario, seed=args.seed).run()
    print_timeline(result, args.every)
    print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
