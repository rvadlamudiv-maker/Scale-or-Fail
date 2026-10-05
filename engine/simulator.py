"""Tick-based flow simulator.

Traffic moves as rates (requests/second) through the graph in topological
order, not as individual requests, so the engine stays fast at millions of
simulated RPS. Day 1: each node serves up to capacity and drops the excess.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from engine.models import ComponentType, SystemGraph
from engine.scenario import Scenario


@dataclass(frozen=True, slots=True)
class NodeTick:
    inbound_rps: float
    served_rps: float
    dropped_rps: float
    load: float  # demand / capacity; > 1.0 means overloaded


@dataclass(frozen=True, slots=True)
class TickSnapshot:
    t: float
    nodes: dict[str, NodeTick]


@dataclass(frozen=True, slots=True)
class NodeSummary:
    avg_inbound_rps: float
    avg_served_rps: float
    peak_served_rps: float
    peak_load: float
    drop_rate: float
    overloaded_s: float


@dataclass(frozen=True, slots=True)
class SimulationResult:
    scenario: Scenario
    snapshots: list[TickSnapshot]

    def summary(self) -> dict[str, NodeSummary]:
        dt = 1.0 / self.scenario.tick_hz
        n = len(self.snapshots)
        out: dict[str, NodeSummary] = {}
        for node_id in self.snapshots[0].nodes:
            ticks = [s.nodes[node_id] for s in self.snapshots]
            inbound = sum(t.inbound_rps for t in ticks)
            dropped = sum(t.dropped_rps for t in ticks)
            out[node_id] = NodeSummary(
                avg_inbound_rps=inbound / n,
                avg_served_rps=sum(t.served_rps for t in ticks) / n,
                peak_served_rps=max(t.served_rps for t in ticks),
                peak_load=max(t.load for t in ticks),
                drop_rate=dropped / inbound if inbound else 0.0,
                overloaded_s=sum(dt for t in ticks if t.load > 1.0),
            )
        return out


class Simulator:
    """Deterministic: same graph + scenario + seed = same result."""

    def __init__(self, graph: SystemGraph, scenario: Scenario, seed: int | None = None) -> None:
        self.graph = graph
        self.scenario = scenario
        self.dt = 1.0 / scenario.tick_hz
        self.total_ticks = round(scenario.duration_s * scenario.tick_hz)
        self._rng = random.Random(scenario.seed if seed is None else seed)
        self._order = graph.topological_order()
        self._tick = 0

    @property
    def done(self) -> bool:
        return self._tick >= self.total_ticks

    def step(self) -> TickSnapshot:
        if self.done:
            raise StopIteration("simulation already finished")
        t = self._tick * self.dt
        inbound: defaultdict[str, float] = defaultdict(float)
        inbound[self.graph.client_id] = self.scenario.traffic.rps_at(t, self._rng)

        nodes: dict[str, NodeTick] = {}
        for node_id in self._order:
            component = self.graph.component(node_id)
            demand = inbound[node_id]
            capacity = component.total_capacity_rps
            served = min(demand, capacity)
            nodes[node_id] = NodeTick(
                inbound_rps=demand,
                served_rps=served,
                dropped_rps=demand - served,
                load=demand / capacity if capacity != float("inf") else 0.0,
            )
            self._route(node_id, component.type, served, inbound)

        self._tick += 1
        return TickSnapshot(t=t, nodes=nodes)

    def _route(self, node_id, kind, served, inbound) -> None:
        edges = self.graph.downstream(node_id)
        if not edges or served == 0:
            return
        if kind is ComponentType.LOAD_BALANCER:
            total_weight = sum(e.weight for e in edges)
            for e in edges:
                inbound[e.target] += served * e.weight / total_weight
        else:
            for e in edges:
                inbound[e.target] += served * e.calls_per_request

    def iter_ticks(self) -> Iterator[TickSnapshot]:
        while not self.done:
            yield self.step()

    def run(self) -> SimulationResult:
        return SimulationResult(scenario=self.scenario, snapshots=list(self.iter_ticks()))
