"""Scenarios define the traffic a design must survive."""

from __future__ import annotations

import datetime
import random
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Spike(BaseModel):
    at_s: float = Field(ge=0, description="When the spike starts (simulated seconds).")
    duration_s: float = Field(gt=0)
    multiplier: float = Field(gt=0, description="Traffic multiplier while the spike is active.")

    def active(self, t: float) -> bool:
        return self.at_s <= t < self.at_s + self.duration_s


class TrafficProfile(BaseModel):
    base_rps: float = Field(gt=0)
    spikes: list[Spike] = Field(default_factory=list)
    noise: float = Field(default=0.0, ge=0, le=0.5, description="Relative random jitter, 0-50%.")

    def rps_at(self, t: float, rng: random.Random) -> float:
        rps = self.base_rps
        for spike in self.spikes:
            if spike.active(t):
                rps *= spike.multiplier
        if self.noise:
            rps *= 1 + rng.uniform(-self.noise, self.noise)
        return rps


class ChaosEvent(BaseModel):
    """Something that goes wrong mid-run.

    kill_instances: `count` instances of `target` die (they come back after duration_s, if set).
    cache_flush:    the `target` cache loses everything and has to warm up again.
    slow_down:      `target` becomes `factor` times slower (and serves `factor` times less).
    gray_failure:   `count` instances of `target` become `factor` times slower but still pass
                    health checks, so they keep getting traffic.
    bad_deploy:     a change that makes `target` `factor` times slower ships. With a global rollout it
                    hits every instance until humans roll it back after duration_s; with a canary
                    rollout it only hits the canary and is rolled back automatically.
    network_partition: the `target` database is cut off from its failover automation for
                    duration_s. Apps can still reach it - but the automation can't.
    """

    at_s: float = Field(ge=0, description="When it happens (simulated seconds).")
    kind: Literal["kill_instances", "cache_flush", "slow_down", "gray_failure", "bad_deploy", "network_partition"]
    target: str = Field(min_length=1, description="Component id it hits.")
    count: int = Field(default=1, ge=1, description="kill_instances / gray_failure: how many instances.")
    factor: float = Field(default=2.0, gt=1, description="slow_down / gray_failure: how many times slower.")
    duration_s: float | None = Field(default=None, gt=0, description="How long it lasts. None = permanent.")

    def label(self) -> str:
        what = {
            "kill_instances": f"{self.count} {self.target} instance(s) killed",
            "cache_flush": f"{self.target} flushed",
            "slow_down": f"{self.target} {self.factor:g}x slower",
            "gray_failure": f"{self.count} {self.target} instance(s) {self.factor:g}x slower, still passing health checks",
            "bad_deploy": f"bad deploy to {self.target} ({self.factor:g}x slower)",
            "network_partition": f"network partition: {self.target} cut off from its failover automation",
        }[self.kind]
        return what + (f" for {self.duration_s:g}s" if self.duration_s else "")


class Goals(BaseModel):
    """What a design must achieve to score well in this scenario."""

    availability: float = Field(default=0.999, gt=0, le=1, description="Share of requests that must succeed.")
    p99_ms: float = Field(default=500, gt=0, description="End-to-end p99 latency target.")
    budget_per_hour: float = Field(default=1500, gt=0, description="Average spend target ($/hour).")
    freshness: float = Field(default=0.999, gt=0, le=1, description="Share of requests that must see fresh data.")
    staleness_tolerance_ms: float = Field(
        default=100, gt=0, description="Replica data older than this counts as stale."
    )
    max_lag_s: float = Field(
        default=60, gt=0, description="Queues: every message should be processed within this many seconds."
    )


class Incident(BaseModel):
    """The real, publicly documented outage a scenario is inspired by."""

    title: str
    date: str
    postmortem_url: str
    summary: str = Field(description="What happened, in our own words.")
    real_fixes: list[str] = Field(default_factory=list, description="What the real engineers did.")

    @field_validator("date", mode="before")
    @classmethod
    def _date_as_text(cls, value):
        # YAML reads an unquoted 2018-10-21 as a date, not text. Accept both.
        return value.isoformat() if isinstance(value, datetime.date) else value


class Scenario(BaseModel):
    name: str
    description: str = ""
    duration_s: float = Field(gt=0)
    tick_hz: int = Field(default=10, ge=1, le=100)
    seed: int = 42
    traffic: TrafficProfile
    goals: Goals = Field(default_factory=Goals)
    events: list[ChaosEvent] = Field(default_factory=list)
    incident: Incident | None = None
    hint: str | None = Field(default=None, description="A nudge for stuck players, without the answer.")
