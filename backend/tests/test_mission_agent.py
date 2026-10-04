import json

from app.mission.agent import MissionAgent


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeModel:
    def __init__(self, response):
        self.response = response

    def invoke(self, messages):
        return FakeResponse(self.response)


def create_agent(
    mission_type,
    priority,
    origin=None,
    destination=None,
):
    agent = MissionAgent()

    response = {
        "mission_type": mission_type,
        "priority": priority,
        "origin": origin,
        "destination": destination,
        "confidence": 0.95,
        "explanation": "Test mission classification.",
    }

    # Replace the entire model instead of modifying ChatOpenAI.
    agent.structured_model = FakeModel(
        json.dumps(response)
    )

    return agent


def test_trauma_mission():
    agent = create_agent(
        "TRAUMA",
        "CRITICAL",
        "Anna Nagar",
        "hospital",
    )

    result = agent.analyze(
        "Take a critically injured patient from Anna Nagar to a hospital immediately."
    )

    assert result.mission_type == "TRAUMA"
    assert result.priority == "CRITICAL"
    assert result.origin == "Anna Nagar"
    assert result.destination == "hospital"


def test_medical_supply_mission():
    agent = create_agent(
        "MEDICAL_SUPPLY",
        "HIGH",
    )

    result = agent.analyze(
        "Deliver blood from the blood bank to the hospital."
    )

    assert result.mission_type == "MEDICAL_SUPPLY"


def test_rescue_mission():
    agent = create_agent(
        "RESCUE",
        "HIGH",
    )

    result = agent.analyze(
        "Send rescue equipment to an area affected by flooding."
    )

    assert result.mission_type == "RESCUE"


def test_relief_mission():
    agent = create_agent(
        "RELIEF",
        "NORMAL",
    )

    result = agent.analyze(
        "Transport food and drinking water to the relief centre."
    )

    assert result.mission_type == "RELIEF"