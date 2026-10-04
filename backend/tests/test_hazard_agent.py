import json

from fastapi.testclient import TestClient

from app.main import app
from app.hazard.agent import HazardAgent


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeModel:
    def __init__(self, response):
        self.response = response

    def invoke(self, messages):
        return FakeResponse(self.response)


def create_hazard_agent():
    agent = HazardAgent(app.state.simulation)

    response = {
        "flood_risk": "MEDIUM",
        "affected_roads": 0,
        "blocked_roads": 0,
        "explanation": "Test hazard status.",
    }

    agent.structured_model = FakeModel(
        json.dumps(response)
    )

    return agent


def setup_simulation():
    client = TestClient(app)

    client.post(
        "/api/simulation",
        json={"scenario": "extreme"},
    )

    client.post("/api/simulation/run")

    return client


def test_trauma_mission():
    with setup_simulation():
        agent = create_hazard_agent()

        result = agent.analyze()

        assert result.flood_risk in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }
        assert result.affected_roads >= 0
        assert result.blocked_roads >= 0
        assert isinstance(result.explanation, str)


def test_medical_supply_mission():
    with setup_simulation():
        agent = create_hazard_agent()

        result = agent.analyze()

        assert result.flood_risk in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }
        assert result.affected_roads >= 0
        assert result.blocked_roads >= 0


def test_rescue_mission():
    with setup_simulation():
        agent = create_hazard_agent()

        result = agent.analyze()

        assert result.flood_risk in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }
        assert result.affected_roads >= 0
        assert result.blocked_roads >= 0


def test_relief_mission():
    with setup_simulation():
        agent = create_hazard_agent()

        result = agent.analyze()

        assert result.flood_risk in {
            "LOW",
            "MEDIUM",
            "HIGH",
            "CRITICAL",
        }
        assert result.affected_roads >= 0
        assert result.blocked_roads >= 0