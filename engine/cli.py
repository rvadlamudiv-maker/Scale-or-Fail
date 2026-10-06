"""Command line runner: python -m engine.cli run SCENARIO DESIGN"""

from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from engine.loader import load_design, load_scenario
from engine.models import ComponentType
from engine.simulator import SimulationResult, Simulator

console = Console()


def _style_for_load(load: float) -> str:
    if load > 1.0:
        return "bold red"
    if load > 0.8:
        return "yellow"
    return "green"


def _style_for_latency(ms: float) -> str:
    if ms > 1000:
        return "bold red"
    if ms > 300:
        return "yellow"
    return "green"


def _style_for_rate(rate: float) -> str:
    if rate > 0.05:
        return "bold red"
    if rate > 0:
        return "yellow"
    return "green"


def _style_for_lag(ms: float) -> str:
    if ms > 500:
        return "bold red"
    if ms > 100:
        return "yellow"
    return "green"


def _fmt(n: float) -> str:
    return f"{n:,.0f}"


def print_timeline(result: SimulationResult, every_s: float) -> None:
    node_ids = list(result.snapshots[0].nodes)
    table = Table(title="Served RPS over time  (-N = failed: dropped + timed out + no connection)")
    table.add_column("t (s)", justify="right")
    for node_id in node_ids:
        table.add_column(node_id, justify="right")
    table.add_column("end-to-end", justify="right")
    step = max(1, round(every_s * result.scenario.tick_hz))
    for snap in result.snapshots[::step]:
        cells = []
        for node_id in node_ids:
            tick = snap.nodes[node_id]
            text = _fmt(tick.served_rps)
            failed = tick.dropped_rps + tick.timed_out_rps + tick.pool_rejected_rps
            if failed > 0:
                text += f" (-{_fmt(failed)})"
            cells.append(f"[{_style_for_load(tick.load)}]{text}[/]")
        e2e = snap.end_to_end_ms
        cells.append(f"[{_style_for_latency(e2e)}]{_fmt(e2e)} ms[/]")
        table.add_row(f"{snap.t:.1f}", *cells)
    console.print(table)


def _notes(result: SimulationResult, node_id: str, s) -> str:
    """Extra detail for special components."""
    kind = result.component_types[node_id]
    if kind is ComponentType.CACHE:
        return f"hit ratio {s.avg_hit_ratio:.0%}"
    if kind is ComponentType.REPLICA:
        lag = s.peak_replication_lag_ms
        return f"[{_style_for_lag(lag)}]lag up to {_fmt(lag)} ms[/]"
    return ""


def print_summary(result: SimulationResult) -> None:
    table = Table(title="Summary")
    columns = ("node", "avg in", "peak load", "peak latency", "failed", "retries", "overloaded", "notes")
    for col in columns:
        table.add_column(col, justify="left" if col in ("node", "notes") else "right")
    for node_id, s in result.summary().items():
        failed = s.drop_rate + s.timeout_rate + s.pool_reject_rate
        table.add_row(
            node_id,
            _fmt(s.avg_inbound_rps),
            f"[{_style_for_load(s.peak_load)}]{s.peak_load:.0%}[/]",
            f"[{_style_for_latency(s.peak_latency_ms)}]{_fmt(s.peak_latency_ms)} ms[/]",
            f"[{_style_for_rate(failed)}]{failed:.1%}[/]",
            f"{s.retry_share:.0%}",
            f"{s.overloaded_s:.1f}s",
            _notes(result, node_id, s),
        )
    console.print(table)
    p50, p99 = result.latency_percentile(50), result.latency_percentile(99)
    console.print(
        f"End-to-end latency:  p50 [{_style_for_latency(p50)}]{_fmt(p50)} ms[/]"
        f"   p99 [{_style_for_latency(p99)}]{_fmt(p99)} ms[/]"
    )


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
