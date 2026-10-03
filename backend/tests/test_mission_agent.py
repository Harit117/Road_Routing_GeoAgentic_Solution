from app.mission.agent import MissionAgent


def test_trauma_mission():
    agent = MissionAgent()

    result = agent.analyze(
        "Take a critically injured patient from Anna Nagar to a hospital immediately."
    )

    assert result.mission_type == "TRAUMA"
    assert result.priority == "CRITICAL"
    assert result.origin == "Anna Nagar"
    assert result.destination == "hospital"


def test_medical_supply_mission():
    agent = MissionAgent()

    result = agent.analyze(
        "Deliver blood from the blood bank to the hospital."
    )

    assert result.mission_type == "MEDICAL_SUPPLY"


def test_rescue_mission():
    agent = MissionAgent()

    result = agent.analyze(
        "Send rescue equipment to an area affected by flooding."
    )

    assert result.mission_type == "RESCUE"


def test_relief_mission():
    agent = MissionAgent()

    result = agent.analyze(
        "Transport food and drinking water to the relief centre."
    )

    assert result.mission_type == "RELIEF"