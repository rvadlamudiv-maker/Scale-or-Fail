"""Turn a simulation result into a score and a grade, like the game's postmortem screen.

Every run starts at 10,000 points:
  - availability below target costs 1,200 points per percentage point (max 6,000)
  - p99 latency above target costs 400 points per doubling (max 3,000)
  - spending under budget earns up to 1,000 points; over budget costs up to 3,000
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from engine.simulator import SimulationResult

BASE_POINTS = 10_000
GRADES = [(10_000, "S"), (9_000, "A"), (7_500, "B"), (6_000, "C"), (4_000, "D"), (0, "F")]


@dataclass(frozen=True, slots=True)
class ScoreLine:
    label: str
    detail: str
    points: int


@dataclass(frozen=True, slots=True)
class ScoreCard:
    lines: list[ScoreLine]
    total: int
    grade: str


def grade_for(total: int) -> str:
    return next(grade for threshold, grade in GRADES if total >= threshold)


def availability_points(availability: float, target: float) -> int:
    shortfall_points = max(0.0, target - availability) * 100  # percentage points below target
    return -min(6000, round(shortfall_points * 1200))


def latency_points(p99_ms: float, target_ms: float) -> int:
    if p99_ms <= target_ms:
        return 0
    return -min(3000, round(400 * math.log2(p99_ms / target_ms)))


def cost_points(cost_per_hour: float, budget: float) -> int:
    if cost_per_hour <= budget:
        return round(1000 * (budget - cost_per_hour) / budget)
    return -min(3000, round(3000 * (cost_per_hour - budget) / budget))


def score(result: SimulationResult) -> ScoreCard:
    goals = result.scenario.goals
    availability = result.availability
    p99 = result.latency_percentile(99)
    cost = result.avg_cost_per_hour
    lines = [
        ScoreLine("Base", "", BASE_POINTS),
        ScoreLine(
            "Availability",
            f"{availability:.2%} vs {goals.availability:.1%} target",
            availability_points(availability, goals.availability),
        ),
        ScoreLine(
            "Latency",
            f"p99 {p99:,.0f} ms vs {goals.p99_ms:,.0f} ms target",
            latency_points(p99, goals.p99_ms),
        ),
        ScoreLine(
            "Cost",
            f"${cost:,.0f}/hr vs ${goals.budget_per_hour:,.0f}/hr budget",
            cost_points(cost, goals.budget_per_hour),
        ),
    ]
    total = max(0, sum(line.points for line in lines))
    return ScoreCard(lines=lines, total=total, grade=grade_for(total))
