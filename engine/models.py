"""Data model for a player's system design: components wired together by edges."""

from __future__ import annotations

import math
from enum import StrEnum
from graphlib import CycleError, TopologicalSorter
from typing import Literal

from pydantic import BaseModel, Field, PrivateAttr, model_validator


class ComponentType(StrEnum):
    CLIENT = "client"
    LOAD_BALANCER = "load_balancer"
    APP_SERVER = "app_server"
    DATABASE = "database"
    CACHE = "cache"
    REPLICA = "replica"


# Requests per second one instance can serve before it saturates.
DEFAULT_CAPACITY_RPS: dict[ComponentType, float] = {
    ComponentType.LOAD_BALANCER: 50_000,
    ComponentType.APP_SERVER: 1_000,
    ComponentType.DATABASE: 5_000,
    ComponentType.CACHE: 50_000,
    ComponentType.REPLICA: 5_000,
}

# Time one request spends being processed when the component is idle (milliseconds).
DEFAULT_SERVICE_MS: dict[ComponentType, float] = {
    ComponentType.LOAD_BALANCER: 1,
    ComponentType.APP_SERVER: 20,
    ComponentType.DATABASE: 5,
    ComponentType.CACHE: 1,
    ComponentType.REPLICA: 5,
}

# What one instance costs to run, in dollars per hour (game prices).
DEFAULT_PRICE_PER_HOUR: dict[ComponentType, float] = {
    ComponentType.CLIENT: 0,
    ComponentType.LOAD_BALANCER: 40,
    ComponentType.APP_SERVER: 90,
    ComponentType.DATABASE: 380,
    ComponentType.CACHE: 120,
    ComponentType.REPLICA: 260,
}

# By default a component can queue up to 1 second of work before it drops requests.
DEFAULT_QUEUE_SECONDS = 1.0


class Component(BaseModel):
    id: str = Field(min_length=1)
    type: ComponentType
    instances: int = Field(default=1, ge=1)
    capacity_rps: float | None = Field(
        default=None, gt=0, description="Per-instance capacity override."
    )
    max_queue: float | None = Field(
        default=None, ge=0, description="Max requests waiting. Default: 1 second of capacity."
    )
    service_ms: float | None = Field(
        default=None, gt=0, description="Processing time per request when idle (ms)."
    )
    timeout_ms: float | None = Field(
        default=None, gt=0, description="Requests waiting longer than this give up. None = wait forever."
    )
    # Cache settings (only used when type is "cache").
    max_hit_ratio: float = Field(default=0.9, ge=0, le=1, description="Share of requests that are cacheable.")
    ttl_s: float = Field(default=300, gt=0, description="How long a cached entry lives (seconds).")
    working_set: int = Field(default=50_000, ge=1, description="Number of distinct hot keys.")
    cold_start: bool = Field(default=False, description="Start with an empty cache.")
    # Replica settings (only used when type is "replica").
    replica_of: str | None = Field(default=None, description="The database this replica copies.")
    # Autoscaling: on when max_instances is set. `instances` is the starting (and minimum) count.
    max_instances: int | None = Field(default=None, ge=1, description="Autoscaling ceiling. None = fixed size.")
    target_utilization: float = Field(default=0.7, gt=0, le=1, description="Scale out to keep load near this.")
    warmup_s: float = Field(default=30, ge=0, description="Seconds before a new instance can serve traffic.")
    scale_in_after_s: float = Field(default=60, ge=0, description="Low load must last this long before scaling in.")
    price_per_hour: float | None = Field(default=None, ge=0, description="Per-instance price override ($/hour).")
    balancing: Literal["round_robin", "least_outstanding"] = Field(
        default="round_robin",
        description="How traffic is spread over this component's instances. least_outstanding sends "
        "less traffic to slow instances (like outlier detection); round_robin sends everyone the same.",
    )

    @property
    def hourly_price(self) -> float:
        """What one instance costs per hour."""
        if self.price_per_hour is not None:
            return self.price_per_hour
        return DEFAULT_PRICE_PER_HOUR[self.type]

    @model_validator(mode="after")
    def _check_autoscaling(self) -> Component:
        if self.max_instances is not None and self.max_instances < self.instances:
            raise ValueError(f"{self.id!r}: max_instances must be >= instances")
        return self

    @property
    def total_capacity_rps(self) -> float:
        if self.type is ComponentType.CLIENT:
            return math.inf
        per_instance = self.capacity_rps or DEFAULT_CAPACITY_RPS[self.type]
        return per_instance * self.instances

    @property
    def queue_limit(self) -> float:
        if self.type is ComponentType.CLIENT:
            return 0.0
        if self.max_queue is not None:
            return self.max_queue
        return self.total_capacity_rps * DEFAULT_QUEUE_SECONDS

    @property
    def service_time_ms(self) -> float:
        if self.type is ComponentType.CLIENT:
            return 0.0
        return self.service_ms or DEFAULT_SERVICE_MS[self.type]


class Edge(BaseModel):
    source: str
    target: str
    weight: float = Field(default=1.0, gt=0, description="Share of traffic when the source is a load balancer.")
    calls_per_request: float = Field(default=1.0, gt=0, description="Downstream calls per request served by the source.")
    retries: int = Field(default=0, ge=0, le=10, description="How many times the source retries a failed call.")
    retry_delay_ms: float = Field(default=100, gt=0, description="How long the source waits before retrying.")
    backoff: Literal["fixed", "exponential"] = Field(
        default="fixed", description="exponential doubles the delay on every retry."
    )
    jitter: bool = Field(default=False, description="Spread each retry randomly over [0, delay].")
    retry_budget: float | None = Field(
        default=None, gt=0, le=1, description="Cap retries at this fraction of first attempts (0.1 = 10%)."
    )
    pool_size: int | None = Field(
        default=None, ge=1, description="Max open connections from source to target. None = unlimited."
    )
    caller_timeout_ms: float | None = Field(
        default=None, gt=0,
        description="The source gives up on a call after this long, but the target still does the work.",
    )
    parallel: bool = Field(
        default=False, description="Make all calls_per_request calls at once and wait for the slowest."
    )

    @model_validator(mode="after")
    def _check_parallel(self) -> Edge:
        if self.parallel and self.calls_per_request != int(self.calls_per_request):
            raise ValueError("parallel calls need a whole number of calls_per_request")
        return self


class SystemGraph(BaseModel):
    """A validated, acyclic system design with exactly one client entry point."""

    components: list[Component]
    edges: list[Edge]

    _by_id: dict[str, Component] = PrivateAttr(default_factory=dict)
    _downstream: dict[str, list[Edge]] = PrivateAttr(default_factory=dict)
    _order: list[str] = PrivateAttr(default_factory=list)

    @model_validator(mode="after")
    def _validate_and_index(self) -> SystemGraph:
        by_id: dict[str, Component] = {}
        for c in self.components:
            if c.id in by_id:
                raise ValueError(f"duplicate component id: {c.id!r}")
            by_id[c.id] = c

        clients = [c for c in self.components if c.type is ComponentType.CLIENT]
        if len(clients) != 1:
            raise ValueError(f"design needs exactly one client, found {len(clients)}")
        client_id = clients[0].id

        downstream: dict[str, list[Edge]] = {cid: [] for cid in by_id}
        predecessors: dict[str, set[str]] = {cid: set() for cid in by_id}
        seen_pairs: set[tuple[str, str]] = set()
        for e in self.edges:
            for end in (e.source, e.target):
                if end not in by_id:
                    raise ValueError(f"edge references unknown component: {end!r}")
            if e.source == e.target:
                raise ValueError(f"self-loop on {e.source!r}")
            if e.target == client_id:
                raise ValueError("nothing may send traffic into the client")
            if (e.source, e.target) in seen_pairs:
                raise ValueError(f"duplicate edge {e.source!r} -> {e.target!r}")
            seen_pairs.add((e.source, e.target))
            downstream[e.source].append(e)
            predecessors[e.target].add(e.source)

        if not downstream[client_id]:
            raise ValueError("the client is not connected to anything")

        # A replica must copy a database, and is simulated after it (it replays its writes).
        for c in self.components:
            if c.type is ComponentType.REPLICA:
                primary = by_id.get(c.replica_of or "")
                if primary is None or primary.type is not ComponentType.DATABASE:
                    raise ValueError(f"replica {c.id!r} must set replica_of to a database id")
                predecessors[c.id].add(primary.id)
            elif c.replica_of is not None:
                raise ValueError(f"only replicas can set replica_of (found it on {c.id!r})")

        try:
            order = list(TopologicalSorter(predecessors).static_order())
        except CycleError as exc:
            raise ValueError(f"design contains a cycle: {exc.args[1]}") from exc

        self._by_id = by_id
        self._downstream = downstream
        self._order = order
        return self

    @property
    def client_id(self) -> str:
        return next(c.id for c in self.components if c.type is ComponentType.CLIENT)

    def component(self, component_id: str) -> Component:
        return self._by_id[component_id]

    def downstream(self, component_id: str) -> list[Edge]:
        return self._downstream[component_id]

    def topological_order(self) -> list[str]:
        return list(self._order)
