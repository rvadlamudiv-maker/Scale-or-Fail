"""Scenarios define the traffic a design must survive."""

from __future__ import annotations

import random

from pydantic import BaseModel, Field


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


class Scenario(BaseModel):
    name: str
    description: str = ""
    duration_s: float = Field(gt=0)
    tick_hz: int = Field(default=10, ge=1, le=100)
    seed: int = 42
    traffic: TrafficProfile
