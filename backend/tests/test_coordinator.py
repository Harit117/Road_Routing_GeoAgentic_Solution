from fastapi.testclient import TestClient

from app.main import app
from app.agent.coordinator import Coordinator
from app.mission.state import MissionState


class FakeMissionService:
    def __init__(self, mission_type, priority):
        self.mission_type = mission_type
        self.priority = priority

    def process_request(self, user_request):
        defaults = {
            "TRAUMA": (0.90, 0.80, 0.90),
            "MEDICAL_SUPPLY": (0.85, 0.75, 0.95),
            "RESCUE": (0.60, 0.90, 0.70),
            "RELIEF": (0.50, 0.75, 0.50),
        }

        time_weight, safety_weight, payload_sensitivity = (
            defaults[self.mission_type]
        )

        if self.mission_type in ["TRAUMA", "MEDICAL_SUPPLY"]:
            facility_type = "hospital"
            destination = "hospital"
        else:
            facility_type = "relief_centre"
            destination = "relief_centre"

        return MissionState(
            mission_type=self.mission_type,
            priority=self.priority,
            origin=None,
            destination=destination,
            time_weight=time_weight,
            safety_weight=safety_weight,
            payload_sensitivity=payload_sensitivity,
            confidence=1.0,
            facility_type=facility_type,
            candidate_facilities=[],
            explanation="Fake mission for testing.",
        )


def create_coordinator():
    with TestClient(app) as client:
        client.post(
            "/api/simulation",
            json={"scenario": "extreme"}
        )
        client.post("/api/simulation/run")

        coordinator = Coordinator(
            app.state.planner,
            app.state.simulation,
        )

    return coordinator


def test_coordinator_processes_mission():
    coordinator = create_coordinator()
    coordinator.mission_service = FakeMissionService(
        "TRAUMA",
        "CRITICAL"
    )

    result = coordinator.process(
        "Take a critically injured patient to a hospital.",
        origin=(80.22, 12.98),
    )

    assert result["mission"]["mission_type"] == "TRAUMA"
    assert result["mission"]["priority"] == "CRITICAL"
    assert result["route"]["mission"] == "medical"


def test_coordinator_medical_supply():
    coordinator = create_coordinator()
    coordinator.mission_service = FakeMissionService(
        "MEDICAL_SUPPLY",
        "HIGH"
    )

    result = coordinator.process(
        "Deliver blood to the hospital.",
        origin=(80.22, 12.98),
    )

    assert result["mission"]["mission_type"] == "MEDICAL_SUPPLY"
    assert result["route"]["mission"] == "medical"


def test_coordinator_rescue():
    coordinator = create_coordinator()
    coordinator.mission_service = FakeMissionService(
        "RESCUE",
        "HIGH"
    )

    result = coordinator.process(
        "Send rescue equipment to a flooded area.",
        origin=(80.22, 12.98),
    )

    assert result["mission"]["mission_type"] == "RESCUE"
    assert result["route"]["mission"] == "evacuation"


def test_coordinator_relief():
    coordinator = create_coordinator()
    coordinator.mission_service = FakeMissionService(
        "RELIEF",
        "NORMAL"
    )

    result = coordinator.process(
        "Transport food and drinking water to the relief centre.",
        origin=(80.22, 12.98),
    )

    assert result["mission"]["mission_type"] == "RELIEF"
    assert result["route"]["mission"] == "evacuation"