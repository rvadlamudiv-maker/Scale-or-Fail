"""Data model for a player's system design: components wired together by edges."""

from __future__ import annotations

import math
from enum import StrEnum
from graphlib import CycleError, TopologicalSorter

from pydantic import BaseModel, Field, PrivateAttr, model_validator


class ComponentType(StrEnum):
    CLIENT = "client"
    LOAD_BALANCER = "load_balancer"
    APP_SERVER = "app_server"
    DATABASE = "database"


# Requests per second one instance can serve before it saturates.
DEFAULT_CAPACITY_RPS: dict[ComponentType, float] = {
    ComponentType.LOAD_BALANCER: 50_000,
    ComponentType.APP_SERVER: 1_000,
    ComponentType.DATABASE: 5_000,
}


class Component(BaseModel):
    id: str = Field(min_length=1)
    type: ComponentType
    instances: int = Field(default=1, ge=1)
    capacity_rps: float | None = Field(
        default=None, gt=0, description="Per-instance capacity override."
    )

    @property
    def total_capacity_rps(self) -> float:
        if self.type is ComponentType.CLIENT:
            return math.inf
        per_instance = self.capacity_rps or DEFAULT_CAPACITY_RPS[self.type]
        return per_instance * self.instances


class Edge(BaseModel):
    source: str
    target: str
    weight: float = Field(default=1.0, gt=0, description="Share of traffic when the source is a load balancer.")
    calls_per_request: float = Field(default=1.0, gt=0, description="Downstream calls per request served by the source.")


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