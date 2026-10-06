"""Tick-based flow simulator.

Traffic moves as rates (requests/second) through the graph in topological
order, not as individual requests, so the engine stays fast at millions of
simulated RPS.

Each node has a queue. Requests it can't serve this tick wait in line; only
when the queue is full are requests dropped. Requests that would wait longer
than a component's timeout give up (time out). Each node also reports a
latency: its service time stretched by utilization (the M/M/1 curve) plus the
time needed to work through the backlog ahead of a new request (Little's Law).

Day 3: callers retry failed calls. Failed traffic on an edge with retries comes
back to the same target after a delay, as extra load, up to the retry limit.
The delay can be fixed or exponential, with optional jitter to spread retries out,
and an optional retry budget caps retries at a fraction of first attempts.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from engine.models import ComponentType, Edge, SystemGraph
from engine.scenario import Scenario

# Utilization is capped below 1.0 so the M/M/1 curve stays finite at saturation.
MAX_UTILIZATION = 0.95


@dataclass(frozen=True, slots=True)
class NodeTick:
    inbound_rps: float  # everything that arrived, first attempts + retries
    retry_rps: float  # the part of inbound_rps that is retries
    served_rps: float
    dropped_rps: float  # rejected because the queue was full
    timed_out_rps: float  # gave up after waiting longer than the timeout
    queue_depth: float  # requests waiting at the end of this tick
    latency_ms: float  # time a request spends at this node (processing + waiting)
    load: float  # demand / capacity; > 1.0 means overloaded


@dataclass(frozen=True, slots=True)
class TickSnapshot:
    t: float
    nodes: dict[str, NodeTick]
    end_to_end_ms: float  # latency a user request sees, summed along its path


@dataclass(frozen=True, slots=True)
class NodeSummary:
    avg_inbound_rps: float
    avg_served_rps: float
    peak_served_rps: float
    peak_load: float
    peak_queue: float
    peak_latency_ms: float
    drop_rate: float
    timeout_rate: float
    retry_share: float  # fraction of all arrivals that were retries
    overloaded_s: float


@dataclass(frozen=True, slots=True)
class SimulationResult:
    scenario: Scenario
    snapshots: list[TickSnapshot]
    client_id: str

    def latency_percentile(self, p: float) -> float:
        """End-to-end latency percentile across the run, weighted by traffic per tick."""
        weighted = sorted(
            (s.end_to_end_ms, s.nodes[self.client_id].inbound_rps) for s in self.snapshots
        )
        total = sum(w for _, w in weighted)
        running = 0.0
        for latency, w in weighted:
            running += w
            if running >= p / 100 * total:
                return latency
        return weighted[-1][0]

    def summary(self) -> dict[str, NodeSummary]:
        dt = 1.0 / self.scenario.tick_hz
        n = len(self.snapshots)
        out: dict[str, NodeSummary] = {}
        for node_id in self.snapshots[0].nodes:
            ticks = [s.nodes[node_id] for s in self.snapshots]
            inbound = sum(t.inbound_rps for t in ticks)
            dropped = sum(t.dropped_rps for t in ticks)
            timed_out = sum(t.timed_out_rps for t in ticks)
            retries = sum(t.retry_rps for t in ticks)
            out[node_id] = NodeSummary(
                avg_inbound_rps=inbound / n,
                avg_served_rps=sum(t.served_rps for t in ticks) / n,
                peak_served_rps=max(t.served_rps for t in ticks),
                peak_load=max(t.load for t in ticks),
                peak_queue=max(t.queue_depth for t in ticks),
                peak_latency_ms=max(t.latency_ms for t in ticks),
                drop_rate=dropped / inbound if inbound else 0.0,
                timeout_rate=timed_out / inbound if inbound else 0.0,
                retry_share=retries / inbound if inbound else 0.0,
                overloaded_s=sum(dt for t in ticks if t.load > 1.0),
            )
        return out


# One batch of traffic travelling along an edge: (edge, attempt number, rate).
# attempt 0 is the first try; attempt 1 is the first retry, and so on.
Arrival = tuple[Edge, int, float]


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
        # Retries waiting to be re-sent, keyed by the tick they arrive on.
        self._pending_retries: defaultdict[int, list[Arrival]] = defaultdict(list)
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

        # Who sent what to each node this tick, so failures can be retried by the right caller.
        arrivals: defaultdict[str, list[Arrival]] = defaultdict(list)
        retry_in: defaultdict[str, float] = defaultdict(float)
        for edge, attempt, rate in self._pending_retries.pop(self._tick, []):
            inbound[edge.target] += rate
            retry_in[edge.target] += rate
            arrivals[edge.target].append((edge, attempt, rate))

        nodes: dict[str, NodeTick] = {}
        for node_id in self._order:
            component = self.graph.component(node_id)
            demand_rps = inbound[node_id]
            capacity_rps = component.total_capacity_rps

            if math.isinf(capacity_rps):
                # The client has no limit: everything it sends goes out this tick.
                served, dropped, timed_out, queue, load = demand_rps * self.dt, 0.0, 0.0, 0.0, 0.0
                latency_ms = 0.0
            else:
                # Work in request counts for this tick, not rates.
                available = self._queues[node_id] + demand_rps * self.dt
                served = min(available, capacity_rps * self.dt)
                queue = available - served
                # Requests that would wait longer than the timeout give up.
                timed_out = 0.0
                if component.timeout_ms is not None:
                    max_waiting = capacity_rps * component.timeout_ms / 1000
                    timed_out = max(0.0, queue - max_waiting)
                    queue -= timed_out
                # Whatever still doesn't fit in the queue is rejected.
                dropped = max(0.0, queue - component.queue_limit)
                queue -= dropped
                load = demand_rps / capacity_rps
                latency_ms = self._latency_ms(component, served / self.dt, queue)

            self._queues[node_id] = queue
            served_rps = served / self.dt
            failed_rps = (dropped + timed_out) / self.dt
            nodes[node_id] = NodeTick(
                inbound_rps=demand_rps,
                retry_rps=retry_in[node_id],
                served_rps=served_rps,
                dropped_rps=dropped / self.dt,
                timed_out_rps=timed_out / self.dt,
                queue_depth=queue,
                latency_ms=latency_ms,
                load=load,
            )
            self._schedule_retries(arrivals[node_id], failed_rps, demand_rps)
            self._route(node_id, component.type, served_rps, inbound, arrivals)

        self._tick += 1
        return TickSnapshot(t=t, nodes=nodes, end_to_end_ms=self._end_to_end_ms(nodes))

    def _schedule_retries(self, arrivals: list[Arrival], failed_rps: float, demand_rps: float) -> None:
        """Each caller's share of this tick's failures comes back later, if it has retries left."""
        if failed_rps == 0 or demand_rps == 0:
            return
        failure_fraction = min(1.0, failed_rps / demand_rps)

        # Retry budget: per edge, retries may not exceed a fraction of this tick's first attempts.
        wanted: defaultdict[int, float] = defaultdict(float)
        first_attempts: defaultdict[int, float] = defaultdict(float)
        for edge, attempt, rate in arrivals:
            if attempt == 0:
                first_attempts[id(edge)] += rate
            if attempt < edge.retries:
                wanted[id(edge)] += rate * failure_fraction

        for edge, attempt, rate in arrivals:
            if attempt >= edge.retries:
                continue  # out of retries: this share of the failures is final
            retry_rate = rate * failure_fraction
            if edge.retry_budget is not None and wanted[id(edge)] > 0:
                allowed = edge.retry_budget * first_attempts[id(edge)]
                retry_rate *= min(1.0, allowed / wanted[id(edge)])
            delay_ms = edge.retry_delay_ms
            if edge.backoff == "exponential":
                delay_ms *= 2**attempt  # 1x, 2x, 4x, 8x ... the base delay
            delay_ticks = max(1, round(delay_ms / 1000 * self.scenario.tick_hz))
            if edge.jitter:
                # "Full jitter": callers pick a random moment in [0, delay], so on average
                # the retries spread evenly over every tick in that window.
                for d in range(1, delay_ticks + 1):
                    self._pending_retries[self._tick + d].append((edge, attempt + 1, retry_rate / delay_ticks))
            else:
                # Everyone waits exactly the same time, so the retries land together.
                self._pending_retries[self._tick + delay_ticks].append((edge, attempt + 1, retry_rate))

    def _end_to_end_ms(self, nodes: dict[str, NodeTick]) -> float:
        """Walk the graph bottom-up: a node's total = its own latency + what it waits on downstream."""
        total: dict[str, float] = {}
        for node_id in reversed(self._order):
            edges = self.graph.downstream(node_id)
            if self.graph.component(node_id).type is ComponentType.LOAD_BALANCER:
                # A request goes to ONE target, so take the weighted average.
                weight_sum = sum(e.weight for e in edges)
                downstream = sum(e.weight / weight_sum * total[e.target] for e in edges)
            else:
                # Each downstream call is made in turn, so their latencies add up.
                downstream = sum(e.calls_per_request * total[e.target] for e in edges)
            total[node_id] = nodes[node_id].latency_ms + downstream
        return total[self.graph.client_id]

    @staticmethod
    def _latency_ms(component, served_rps: float, queue: float) -> float:
        capacity_rps = component.total_capacity_rps
        # M/M/1: as a server gets busier, each request waits longer: S / (1 - rho).
        rho = min(served_rps / capacity_rps, MAX_UTILIZATION)
        processing_s = (component.service_time_ms / 1000) / (1 - rho)
        # Little's Law (L = lambda * W): a backlog of L drained at capacity waits W = L / capacity.
        backlog_wait_s = queue / capacity_rps
        return (processing_s + backlog_wait_s) * 1000

    def _route(self, node_id, kind, served_rps, inbound, arrivals) -> None:
        edges = self.graph.downstream(node_id)
        if not edges or served_rps == 0:
            return
        if kind is ComponentType.LOAD_BALANCER:
            total_weight = sum(e.weight for e in edges)
            for e in edges:
                rate = served_rps * e.weight / total_weight
                inbound[e.target] += rate
                arrivals[e.target].append((e, 0, rate))
        else:
            for e in edges:
                rate = served_rps * e.calls_per_request
                inbound[e.target] += rate
                arrivals[e.target].append((e, 0, rate))

    def iter_ticks(self) -> Iterator[TickSnapshot]:
        while not self.done:
            yield self.step()

    def run(self) -> SimulationResult:
        return SimulationResult(
            scenario=self.scenario,
            snapshots=list(self.iter_ticks()),
            client_id=self.graph.client_id,
        )
