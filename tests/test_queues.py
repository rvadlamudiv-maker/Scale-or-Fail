"""Message queues: async work, partitions, backlogs, lost messages and redelivery."""

from pathlib import Path

import yaml

from engine.loader import load_design, load_scenario
from engine.models import SystemGraph
from engine.scenario import Scenario
from engine.scoring import score
from engine.simulator import Simulator

TICKET_RUSH = Path(__file__).resolve().parent.parent / "incidents" / "ticket_rush"


def design(workers=4, partitions=4, max_backlog=1_000_000, db_instances=1):
    return SystemGraph.model_validate(
        {
            "components": [
                {"id": "client", "type": "client"},
                {"id": "q", "type": "queue", "partitions": partitions, "max_backlog": max_backlog},
                {"id": "workers", "type": "app_server", "instances": workers},
                {"id": "db", "type": "database", "instances": db_instances},
            ],
            "edges": [
                {"source": "client", "target": "q"},
                {"source": "q", "target": "workers"},
                {"source": "workers", "target": "db"},
            ],
        }
    )


def scenario(rps=3000, duration_s=20, events=()):
    return Scenario.model_validate(
        {"name": "t", "duration_s": duration_s, "traffic": {"base_rps": rps}, "events": list(events)}
    )


def test_users_only_wait_for_the_queue():
    # Consumers that can't keep up don't slow users down or fail their requests...
    result = Simulator(design(workers=2), scenario(rps=3000)).run()
    assert result.availability == 1.0
    assert result.latency_percentile(99) < 20
    # ...the work just waits: 1,000 more messages a second than 2 workers can take.
    assert result.snapshots[-1].nodes["q"].queue_depth > 15_000
    assert result.peak_message_lag_s > 5


def test_partitions_cap_how_many_consumers_help():
    four = Simulator(design(workers=4, partitions=4), scenario(rps=6000)).run()
    eight_idle = Simulator(design(workers=8, partitions=4), scenario(rps=6000)).run()
    eight = Simulator(design(workers=8, partitions=8, db_instances=2), scenario(rps=6000)).run()
    # Four extra workers do nothing without partitions for them to read...
    assert eight_idle.peak_message_lag_s == four.peak_message_lag_s > 5
    # ...and cost money anyway. With 8 partitions they keep up.
    assert eight_idle.avg_cost_per_hour > four.avg_cost_per_hour
    assert eight.peak_message_lag_s < 0.5


def test_a_full_backlog_loses_messages():
    result = Simulator(design(workers=2, max_backlog=5_000), scenario(rps=3000)).run()
    assert result.lost_messages > 10_000
    assert result.availability == 1.0  # the users were told it worked - which makes it worse
    assert score(result).lines[-2].label == "Message queue"
    assert score(result).lines[-2].points == -3000


def test_failed_messages_are_redelivered_not_lost():
    # The database is down for 5 s: processing fails, but the messages come back and get done.
    outage = [{"at_s": 5, "kind": "kill_instances", "target": "db", "count": 1, "duration_s": 5}]
    result = Simulator(design(workers=6, partitions=8), scenario(rps=3000, events=outage)).run()
    assert result.availability == 1.0
    assert result.lost_messages == 0
    assert result.peak_message_lag_s > 1
    assert result.snapshots[-1].nodes["q"].queue_depth < 1  # caught up by the end


def test_designs_without_a_queue_score_as_before():
    result = Simulator(load_design(TICKET_RUSH / "starter.yaml"), load_scenario(TICKET_RUSH / "scenario.yaml")).run()
    assert "Message queue" not in [line.label for line in score(result).lines]


def test_ticket_rush_a_queue_beats_buying_a_bigger_database():
    scenario = load_scenario(TICKET_RUSH / "scenario.yaml")
    brute = yaml.safe_load(open(TICKET_RUSH / "starter.yaml"))
    next(c for c in brute["components"] if c["id"] == "checkout")["instances"] = 12
    next(c for c in brute["components"] if c["id"] == "inventory")["instances"] = 2
    big = Simulator(SystemGraph.model_validate(brute), scenario).run()
    queued = Simulator(load_design(TICKET_RUSH / "solution.yaml"), scenario).run()
    # Both survive the rush; the queue does it for less, and the line clears within the target.
    assert big.availability > 0.999 and queued.availability > 0.999
    assert queued.avg_cost_per_hour < big.avg_cost_per_hour
    assert queued.peak_message_lag_s < scenario.goals.max_lag_s
    assert score(queued).total > score(big).total
