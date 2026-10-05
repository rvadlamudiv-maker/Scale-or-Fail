"""Tick-based flow simulator.

Traffic moves as rates (requests/second) through the graph in topological
order, not as individual requests, so the engine stays fast at millions of
simulated RPS.

Day 2: each node has a queue. Requests it can't serve this tick wait in line;
only when the queue is full are requests dropped. Each node also reports a
latency: its service time stretched by utilization (the M/M/1 curve) plus the
time needed to work through the backlog ahead of a new request (Little's Law).
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from engine.models import ComponentType, SystemGraph
from engine.scenario import Scenario

# Utilization is capped below 1.0 so the M/M/1 curve stays finite at saturation.
MAX_UTILIZATION = 0.95


@dataclass(frozen=True, slots=True)
class NodeTick:
    inbound_rps: float
    served_rps: float
    dropped_rps: float
    queue_depth: float  # requests waiting at the end of this tick
    latency_ms: float  # time a request spends at this node (processing + waiting)
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
    peak_queue: float
    peak_latency_ms: float
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
                peak_queue=max(t.queue_depth for t in ticks),
                peak_latency_ms=max(t.latency_ms for t in ticks),
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
        self._queues: dict[str, float] = {node_id: 0.0 for node_id in self._order}
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
            demand_rps = inbound[node_id]
            capacity_rps = component.total_capacity_rps

            if math.isinf(capacity_rps):
                # The client has no limit: everything it sends goes out this tick.
                served, dropped, queue, load = demand_rps * self.dt, 0.0, 0.0, 0.0
                latency_ms = 0.0
            else:
                # Work in request counts for this tick, not rates.
                available = self._queues[node_id] + demand_rps * self.dt
                served = min(available, capacity_rps * self.dt)
                queue = available - served
                dropped = max(0.0, queue - component.queue_limit)
                queue -= dropped
                load = demand_rps / capacity_rps
                latency_ms = self._latency_ms(component, served / self.dt, queue)

            self._queues[node_id] = queue
            served_rps = served / self.dt
            nodes[node_id] = NodeTick(
                inbound_rps=demand_rps,
                served_rps=served_rps,
                dropped_rps=dropped / self.dt,
                queue_depth=queue,
                latency_ms=latency_ms,
                load=load,
            )
            self._route(node_id, component.type, served_rps, inbound)

        self._tick += 1
        return TickSnapshot(t=t, nodes=nodes)

    @staticmethod
    def _latency_ms(component, served_rps: float, queue: float) -> float:
        capacity_rps = component.total_capacity_rps
        # M/M/1: as a server gets busier, each request waits longer: S / (1 - rho).
        rho = min(served_rps / capacity_rps, MAX_UTILIZATION)
        processing_s = (component.service_time_ms / 1000) / (1 - rho)
        # Little's Law (L = lambda * W): a backlog of L drained at capacity waits W = L / capacity.
        backlog_wait_s = queue / capacity_rps
        return (processing_s + backlog_wait_s) * 1000

    def _route(self, node_id, kind, served_rps, inbound) -> None:
        edges = self.graph.downstream(node_id)
        if not edges or served_rps == 0:
            return
        if kind is ComponentType.LOAD_BALANCER:
            total_weight = sum(e.weight for e in edges)
            for e in edges:
                inbound[e.target] += served_rps * e.weight / total_weight
        else:
            for e in edges:
                inbound[e.target] += served_rps * e.calls_per_request

    def iter_ticks(self) -> Iterator[TickSnapshot]:
        while not self.done:
            yield self.step()

    def run(self) -> SimulationResult:
        return SimulationResult(scenario=self.scenario, snapshots=list(self.iter_ticks()))
