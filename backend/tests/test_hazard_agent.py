from fastapi.testclient import TestClient

from app.main import app
from app.hazard.agent import HazardAgent


def test_hazard_agent():
    with TestClient(app) as client:

        # Start an extreme rainfall scenario.
        client.post(
            "/api/simulation",
            json={"scenario": "extreme"},
        )

        # Advance the simulation.
        client.post("/api/simulation/run")

        # Give the real simulation to the Hazard Agent.
        agent = HazardAgent(app.state.simulation)

        result = agent.analyze()

        # The agent must return a valid hazard classification.
        assert result.flood_risk in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }

        # These values must never be negative.
        assert result.affected_roads >= 0
        assert result.blocked_roads >= 0

        # Blocked roads are a subset of affected roads.
        assert result.blocked_roads <= result.affected_roads