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

Caches serve hits themselves and forward only misses downstream. Their hit ratio
follows a TTL-cache model and warms up gradually after a cold start.

Connection pools limit how many calls can be in flight on an edge at once. By
Little's Law a pool of N connections carries at most N / latency calls per
second, so when the target slows down, the pool runs dry and calls are rejected.

Read replicas take read traffic off a database, but every replica must also
replay every write the primary accepts. When a replica falls behind, its
replication lag grows and the reads it serves are stale.

Autoscaling adds instances when load runs above a target utilization, but a new
instance only starts serving after its warm-up time, so it can arrive late.

Every instance costs money per hour, including instances that are still booting.

Each tick also estimates availability: the chance a user request succeeds, walking
the graph bottom-up. A call succeeds if its target and everything the target
depends on succeed; retries give failed calls extra chances.

Chaos events break things mid-run: kill instances, flush a cache, slow a component down.

Wasted work: when a caller times out (caller_timeout_ms), the target doesn't know.
It still processes the request, using capacity for an answer nobody is waiting for,
and the caller may retry. That feedback loop can keep a system overloaded after the
trigger is gone: a metastable failure.

Tail-latency amplification: a parallel fan-out waits for its slowest call. With
exponential response times (mean m), the slowest of N takes m * H_N on average,
where H_N = 1 + 1/2 + ... + 1/N, so the more you fan out, the more the tail hurts.

Gray failures: some instances get slow but still pass health checks. With
round-robin balancing they keep getting an equal share of traffic and drown;
least-outstanding balancing notices they are slow and sends them less.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from engine.models import DEFAULT_QUEUE_SECONDS, ComponentType, Edge, SystemGraph
from engine.scenario import Scenario

# Utilization is capped below 1.0 so the M/M/1 curve stays finite at saturation.
MAX_UTILIZATION = 0.95

# How far behind a healthy replica runs (network + apply time), in milliseconds.
BASE_REPLICATION_LAG_MS = 10


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
    hit_ratio: float = 0.0  # caches only: share of requests served from the cache
    pool_rejected_rps: float = 0.0  # calls that never got a connection to this node
    wasted_rps: float = 0.0  # served, but the caller had already given up (wasted work)
    replication_rps: float = 0.0  # replicas only: writes replayed from the primary
    replication_lag_ms: float = 0.0  # replicas only: how far behind the primary it is
    instances: int = 0  # instances serving traffic this tick
    booting_instances: int = 0  # instances launched but still warming up
    cost_per_hour: float = 0.0  # (serving + booting instances) * price per instance


@dataclass(frozen=True, slots=True)
class TickSnapshot:
    t: float
    nodes: dict[str, NodeTick]
    end_to_end_ms: float  # latency a user request sees, summed along its path
    cost_per_hour: float = 0.0  # what the whole design costs to run right now
    success_ratio: float = 1.0  # chance a user request succeeds end to end
    events: tuple[str, ...] = ()  # chaos events that started or ended this tick


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
    pool_reject_rate: float  # calls rejected for lack of a connection, vs. calls attempted
    wasted_rate: float  # work done for callers that had already given up, vs. calls attempted
    avg_hit_ratio: float  # caches only
    peak_replication_lag_ms: float  # replicas only
    avg_instances: float
    peak_instances: int
    avg_cost_per_hour: float
    overloaded_s: float


@dataclass(frozen=True, slots=True)
class SimulationResult:
    scenario: Scenario
    snapshots: list[TickSnapshot]
    client_id: str
    component_types: dict[str, ComponentType]

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

    @property
    def availability(self) -> float:
        """Share of user requests that succeeded, weighted by traffic per tick."""
        weights = [s.nodes[self.client_id].inbound_rps for s in self.snapshots]
        total = sum(weights)
        if total == 0:
            return 1.0
        return sum(s.success_ratio * w for s, w in zip(self.snapshots, weights)) / total

    @property
    def avg_cost_per_hour(self) -> float:
        return sum(s.cost_per_hour for s in self.snapshots) / len(self.snapshots)

    @property
    def peak_cost_per_hour(self) -> float:
        return max(s.cost_per_hour for s in self.snapshots)

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
            pool_rejected = sum(t.pool_rejected_rps for t in ticks)
            wasted = sum(t.wasted_rps for t in ticks)
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
                pool_reject_rate=pool_rejected / (inbound + pool_rejected) if inbound + pool_rejected else 0.0,
                wasted_rate=wasted / (inbound + pool_rejected) if inbound + pool_rejected else 0.0,
                avg_hit_ratio=sum(t.hit_ratio for t in ticks) / n,
                peak_replication_lag_ms=max(t.replication_lag_ms for t in ticks),
                avg_instances=sum(t.instances for t in ticks) / n,
                peak_instances=max(t.instances for t in ticks),
                avg_cost_per_hour=sum(t.cost_per_hour for t in ticks) / n,
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
        # Current hit ratio of every cache.
        self._hit_ratios: dict[str, float] = {}
        # Autoscaling state: instances serving now, instances booting (ready_tick, count),
        # and since when load has been low enough to scale in.
        self._instances: dict[str, int] = {n: graph.component(n).instances for n in self._order}
        self._booting: defaultdict[str, list[tuple[int, int]]] = defaultdict(list)
        self._low_load_since: dict[str, int | None] = {n: None for n in self._order}
        # Chaos: how many times slower each node currently runs.
        self._slowdown: dict[str, float] = {n: 1.0 for n in self._order}
        # Gray failures: (how many instances, how many times slower), and their own backlog.
        self._gray: dict[str, tuple[int, float]] = {n: (0, 1.0) for n in self._order}
        self._gray_queues: dict[str, float] = {n: 0.0 for n in self._order}
        # Events aimed at a component this design doesn't have (e.g. flushing a cache in a
        # design without one) simply don't happen; the rest must make sense.
        self._events = [e for e in scenario.events if e.target in self._instances]
        self._skipped_events = [e for e in scenario.events if e.target not in self._instances]
        for event in self._events:
            if event.kind == "cache_flush" and graph.component(event.target).type is not ComponentType.CACHE:
                raise ValueError(f"cache_flush needs a cache, but {event.target!r} is not one")
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

        event_labels = self._apply_chaos()

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
            self._finish_booting(node_id)
            pool_rejected_rps = self._apply_connection_pools(node_id, arrivals[node_id], inbound)
            replication_rps = 0.0
            if component.type is ComponentType.REPLICA:
                # Every replica instance replays every write the primary accepted this tick.
                replication_rps = nodes[component.replica_of].served_rps * self._instances[node_id]
                inbound[node_id] += replication_rps
            demand_rps = inbound[node_id]
            capacity_rps = self._capacity_rps(node_id)

            if math.isinf(capacity_rps):
                # The client has no limit: everything it sends goes out this tick.
                self._queues[node_id] = 0.0
                served, dropped, timed_out, queue, load = demand_rps * self.dt, 0.0, 0.0, 0.0, 0.0
                latency_ms = 0.0
            elif capacity_rps <= 0:
                # Every instance is down: everything that arrives (or was waiting) fails.
                served, timed_out, queue, latency_ms = 0.0, 0.0, 0.0, 0.0
                dropped = self._queues[node_id] + self._gray_queues[node_id] + demand_rps * self.dt
                self._queues[node_id] = self._gray_queues[node_id] = 0.0
                load = 10.0 if demand_rps > 0 else 0.0
            else:
                served, dropped, timed_out, queue, latency_ms = self._serve(node_id, component, demand_rps, capacity_rps)
                load = demand_rps / capacity_rps

            served_rps = served / self.dt
            failed_rps = (dropped + timed_out) / self.dt
            hit_ratio = 0.0
            if component.type is ComponentType.CACHE:
                hit_ratio = self._update_hit_ratio(node_id, component, demand_rps)
            late_calls = self._late_calls(arrivals[node_id], served_rps, demand_rps, latency_ms, queue, capacity_rps)
            wasted_rps = sum(rate for _, _, rate in late_calls)
            booting = sum(count for _, count in self._booting[node_id])
            replication_lag_ms = 0.0
            if component.type is ComponentType.REPLICA:
                replication_lag_ms = BASE_REPLICATION_LAG_MS + queue / capacity_rps * 1000
            nodes[node_id] = NodeTick(
                inbound_rps=demand_rps,
                retry_rps=retry_in[node_id],
                served_rps=served_rps,
                dropped_rps=dropped / self.dt,
                timed_out_rps=timed_out / self.dt,
                queue_depth=queue,
                latency_ms=latency_ms,
                load=load,
                hit_ratio=hit_ratio,
                pool_rejected_rps=pool_rejected_rps,
                wasted_rps=wasted_rps,
                replication_rps=replication_rps,
                replication_lag_ms=replication_lag_ms,
                instances=self._instances[node_id],
                booting_instances=booting,
                cost_per_hour=(self._instances[node_id] + booting) * component.hourly_price,
            )
            if component.max_instances is not None:
                self._autoscale(node_id, component, demand_rps)
            self._schedule_retries(arrivals[node_id], failed_rps, demand_rps)
            if wasted_rps > 0:
                self._schedule_retries(late_calls, wasted_rps, wasted_rps)  # the caller saw these fail
            # Only real requests go downstream: not cache hits, not replicated writes.
            read_share = 1 - replication_rps / demand_rps if demand_rps else 1.0
            self._route(node_id, component.type, served_rps * (1 - hit_ratio) * read_share, inbound, arrivals)

        self._tick += 1
        return TickSnapshot(
            t=t,
            nodes=nodes,
            end_to_end_ms=self._end_to_end_ms(nodes),
            cost_per_hour=sum(n.cost_per_hour for n in nodes.values()),
            success_ratio=self._success_ratio(nodes),
            events=tuple(event_labels),
        )

    def _success_ratio(self, nodes: dict[str, NodeTick]) -> float:
        """Bottom-up, like end-to-end latency: a node's success = its own success rate
        times the success of the calls it makes (each call made calls_per_request times)."""
        ok: dict[str, float] = {}
        for node_id in reversed(self._order):
            n = nodes[node_id]
            attempted = n.inbound_rps + n.pool_rejected_rps
            failed = n.dropped_rps + n.timed_out_rps + n.pool_rejected_rps + n.wasted_rps
            own = 1 - min(1.0, failed / attempted) if attempted > 0 else 1.0
            edges = self.graph.downstream(node_id)
            if self.graph.component(node_id).type is ComponentType.LOAD_BALANCER:
                weight_sum = sum(e.weight for e in edges)
                downstream = sum(e.weight / weight_sum * self._call_success(e, ok) for e in edges)
            else:
                downstream = math.prod(self._call_success(e, ok) ** e.calls_per_request for e in edges)
                # A cache hit never goes downstream.
                downstream = n.hit_ratio + (1 - n.hit_ratio) * downstream
            ok[node_id] = own * downstream
        return ok[self.graph.client_id]

    @staticmethod
    def _call_success(edge: Edge, ok: dict[str, float]) -> float:
        """A call fails only if every attempt fails. A retry budget limits the extra attempts."""
        fail = 1 - ok[edge.target]
        if fail == 0 or edge.retries == 0:
            return 1 - fail
        extra_attempts = edge.retries
        if edge.retry_budget is not None:
            extra_attempts = min(extra_attempts, edge.retry_budget / fail)
        return 1 - fail ** (1 + extra_attempts)

    def _capacity_rps(self, node_id: str) -> float:
        component = self.graph.component(node_id)
        per_instance = component.total_capacity_rps / component.instances
        return per_instance * self._instances[node_id] / self._slowdown[node_id]

    def _run_queue(self, component, queue: float, demand_rps: float, capacity_rps: float):
        """One tick of one queue, in request counts: serve, then time out, then drop the overflow."""
        available = queue + demand_rps * self.dt
        served = min(available, capacity_rps * self.dt)
        queue = available - served
        # Requests that would wait longer than the timeout give up.
        timed_out = 0.0
        if component.timeout_ms is not None:
            max_waiting = capacity_rps * component.timeout_ms / 1000
            timed_out = max(0.0, queue - max_waiting)
            queue -= timed_out
        # Whatever still doesn't fit in the queue is rejected.
        dropped = max(0.0, queue - self._queue_limit(component, capacity_rps))
        queue -= dropped
        return served, dropped, timed_out, queue

    def _serve(self, node_id: str, component, demand_rps: float, capacity_rps: float):
        """Serve this tick's traffic. Healthy and gray (slow) instances get separate queues."""
        service_ms = self._service_ms(node_id)
        instances = self._instances[node_id]
        gray_count, factor = self._gray[node_id]
        gray_count = min(gray_count, instances)
        if gray_count == 0:
            served, dropped, timed_out, queue = self._run_queue(
                component, self._queues[node_id], demand_rps, capacity_rps
            )
            self._queues[node_id] = queue
            latency_ms = self._latency_ms(service_ms, capacity_rps, served / self.dt, queue)
            return served, dropped, timed_out, queue, latency_ms

        per_instance = capacity_rps / instances
        healthy_capacity = per_instance * (instances - gray_count)
        gray_capacity = per_instance * gray_count / factor
        if component.balancing == "least_outstanding":
            # Slow instances finish fewer requests, so they hold more outstanding ones and get picked less.
            gray_share = gray_capacity / (healthy_capacity + gray_capacity)
        else:
            gray_share = gray_count / instances  # round robin: everyone gets the same share

        totals = [0.0, 0.0, 0.0, 0.0]
        weighted_latency = 0.0
        parts = [
            (self._queues, healthy_capacity, 1 - gray_share, service_ms),
            (self._gray_queues, gray_capacity, gray_share, service_ms * factor),
        ]
        for queues, part_capacity, share, part_service_ms in parts:
            if part_capacity <= 0:
                continue
            result = self._run_queue(component, queues[node_id], demand_rps * share, part_capacity)
            queues[node_id] = result[3]
            totals = [a + b for a, b in zip(totals, result)]
            part_latency = self._latency_ms(part_service_ms, part_capacity, result[0] / self.dt, result[3])
            weighted_latency += share * part_latency
        served, dropped, timed_out, queue = totals
        return served, dropped, timed_out, queue, weighted_latency

    def _service_ms(self, node_id: str) -> float:
        return self.graph.component(node_id).service_time_ms * self._slowdown[node_id]

    def _apply_chaos(self) -> list[str]:
        """Start or end chaos events scheduled for this tick. Returns what happened."""
        labels = []
        if self._tick == 0:
            labels += [f"skipped: {e.label()} (no {e.target!r} in this design)" for e in self._skipped_events]
        hz = self.scenario.tick_hz
        for event in self._events:
            start = round(event.at_s * hz)
            end = round((event.at_s + event.duration_s) * hz) if event.duration_s else None
            if self._tick == start:
                labels.append(event.label())
                if event.kind == "kill_instances":
                    self._instances[event.target] = max(0, self._instances[event.target] - event.count)
                elif event.kind == "cache_flush":
                    self._hit_ratios[event.target] = 0.0
                elif event.kind == "slow_down":
                    self._slowdown[event.target] = event.factor
                elif event.kind == "gray_failure":
                    self._gray[event.target] = (event.count, event.factor)
            elif self._tick == end:
                labels.append(f"recovered: {event.label()}")
                if event.kind == "kill_instances":
                    self._instances[event.target] += event.count
                elif event.kind == "slow_down":
                    self._slowdown[event.target] = 1.0
                elif event.kind == "gray_failure":
                    self._gray[event.target] = (0, 1.0)
                    # Requests still waiting on the (now healthy again) instances join the main queue.
                    self._queues[event.target] += self._gray_queues[event.target]
                    self._gray_queues[event.target] = 0.0
        return labels

    @staticmethod
    def _queue_limit(component, capacity_rps: float) -> float:
        if component.max_queue is not None:
            return component.max_queue
        return capacity_rps * DEFAULT_QUEUE_SECONDS

    def _finish_booting(self, node_id: str) -> None:
        """Instances whose warm-up is over start serving."""
        still_booting = []
        for ready_tick, count in self._booting[node_id]:
            if ready_tick <= self._tick:
                self._instances[node_id] += count
            else:
                still_booting.append((ready_tick, count))
        self._booting[node_id] = still_booting

    def _autoscale(self, node_id: str, component, demand_rps: float) -> None:
        """Target tracking: aim for enough instances to run at target_utilization."""
        per_instance = component.total_capacity_rps / component.instances
        wanted = math.ceil(demand_rps / (per_instance * component.target_utilization))
        wanted = max(component.instances, min(component.max_instances, wanted))
        serving = self._instances[node_id]
        booting = sum(count for _, count in self._booting[node_id])

        if wanted > serving + booting:
            # Scale out now, but the new instances only help after warming up.
            ready_tick = self._tick + max(1, round(component.warmup_s / self.dt))
            self._booting[node_id].append((ready_tick, wanted - serving - booting))
            self._low_load_since[node_id] = None
        elif wanted < serving and not booting:
            # Scale in only after load has stayed low for scale_in_after_s.
            since = self._low_load_since[node_id]
            if since is None:
                self._low_load_since[node_id] = self._tick
            elif (self._tick - since) * self.dt >= component.scale_in_after_s:
                self._instances[node_id] = wanted
                self._low_load_since[node_id] = None
        else:
            self._low_load_since[node_id] = None

    def _apply_connection_pools(self, node_id: str, arrivals: list[Arrival], inbound) -> float:
        """Cap each pooled edge into this node at the rate its connections can carry.

        Rejected calls never reach the node; they count as failures (and may be retried).
        Returns the rejected rate.
        """
        component = self.graph.component(node_id)
        per_edge: defaultdict[int, float] = defaultdict(float)
        for edge, _, rate in arrivals:
            per_edge[id(edge)] += rate

        kept: list[Arrival] = []
        rejected: list[Arrival] = []
        for edge, attempt, rate in arrivals:
            if edge.pool_size is None or per_edge[id(edge)] == 0:
                kept.append((edge, attempt, rate))
                continue
            max_rps = self._pool_limit_rps(
                self._service_ms(node_id), self._capacity_rps(node_id), edge.pool_size, self._queues[node_id]
            )
            allowed = min(1.0, max_rps / per_edge[id(edge)])
            kept.append((edge, attempt, rate * allowed))
            if allowed < 1.0:
                rejected.append((edge, attempt, rate * (1 - allowed)))

        rejected_rps = sum(rate for _, _, rate in rejected)
        if rejected_rps > 0:
            arrivals[:] = kept
            inbound[node_id] -= rejected_rps
            self._schedule_retries(rejected, rejected_rps, rejected_rps)  # every rejected call failed
        return rejected_rps

    @staticmethod
    def _pool_limit_rps(service_ms: float, capacity_rps: float, pool_size: int, queue: float) -> float:
        """The highest call rate whose in-flight calls fit in the pool.

        Little's Law: in-flight calls = rate * latency. Latency itself rises with the rate
        (M/M/1) and with any backlog, so search for the rate where rate * latency = pool_size.
        """
        if capacity_rps <= 0:
            return 0.0

        def in_flight(rate: float) -> float:
            rho = min(rate / capacity_rps, MAX_UTILIZATION)
            latency_s = service_ms / 1000 / (1 - rho) + queue / capacity_rps
            return rate * latency_s

        low, high = 0.0, 100 * capacity_rps
        for _ in range(60):  # binary search: in_flight() only grows with the rate
            mid = (low + high) / 2
            if in_flight(mid) <= pool_size:
                low = mid
            else:
                high = mid
        return low

    @staticmethod
    def _late_calls(arrivals, served_rps, demand_rps, latency_ms, queue, capacity_rps) -> list[Arrival]:
        """Served calls whose caller timed out first.

        A call waits behind the backlog (a fixed wait, queue / capacity) and is then processed
        (an exponential time, M/M/1). If the backlog alone exceeds the caller's timeout, every
        served call is late; otherwise the chance is exp(-(timeout - wait) / processing).
        """
        if served_rps == 0 or demand_rps == 0 or capacity_rps <= 0 or math.isinf(capacity_rps):
            return []
        wait_ms = queue / capacity_rps * 1000
        processing_ms = max(latency_ms - wait_ms, 1e-9)
        late = []
        for edge, attempt, rate in arrivals:
            if edge.caller_timeout_ms is None:
                continue
            slack_ms = edge.caller_timeout_ms - wait_ms
            late_fraction = 1.0 if slack_ms <= 0 else math.exp(-slack_ms / processing_ms)
            served_share = rate * min(1.0, served_rps / demand_rps)
            if late_fraction * served_share > 0:
                late.append((edge, attempt, served_share * late_fraction))
        return late

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

    def _update_hit_ratio(self, node_id: str, component, demand_rps: float) -> float:
        """TTL cache: after a miss, a key stays cached for ttl_s, so a key requested r times
        per second hits r*T / (1 + r*T) of the time. Traffic is spread over the working set."""
        per_key_rate = demand_rps / component.working_set
        x = per_key_rate * component.ttl_s
        target = component.max_hit_ratio * x / (1 + x)
        current = self._hit_ratios.get(node_id)
        if current is None:
            current = 0.0 if component.cold_start else target
        elif demand_rps > 0:
            # Filling up takes about as long as it takes every hot key to be requested once.
            warmup_s = component.working_set / demand_rps
            current += (target - current) * min(1.0, self.dt / warmup_s)
        self._hit_ratios[node_id] = current
        return current

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
                # Sequential calls add up; a parallel fan-out waits for its slowest call.
                downstream = sum(self._call_latency_ms(e, total[e.target]) for e in edges)
                # A cache only goes downstream on a miss.
                downstream *= 1 - nodes[node_id].hit_ratio
            total[node_id] = nodes[node_id].latency_ms + downstream
        return total[self.graph.client_id]

    @staticmethod
    def _call_latency_ms(edge: Edge, target_ms: float) -> float:
        """Time a caller spends on its calls_per_request calls to one target."""
        if edge.parallel:
            n = int(edge.calls_per_request)
            harmonic = sum(1 / k for k in range(1, n + 1))  # H_N: expected max of N exponentials / mean
            return target_ms * harmonic
        return edge.calls_per_request * target_ms

    @staticmethod
    def _latency_ms(service_ms: float, capacity_rps: float, served_rps: float, queue: float) -> float:
        # M/M/1: as a server gets busier, each request waits longer: S / (1 - rho).
        rho = min(served_rps / capacity_rps, MAX_UTILIZATION)
        processing_s = (service_ms / 1000) / (1 - rho)
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
            component_types={c.id: c.type for c in self.graph.components},
        )
