from app.mission.mission_service import MissionService
from app.mission.schemas import MissionProfile


class FakeMissionAgent:
    def __init__(self, mission_type, priority):
        self.mission_type = mission_type
        self.priority = priority

    def analyze(self, user_request):
        defaults = {
            "TRAUMA": (0.90, 0.80, 0.90),
            "MEDICAL_SUPPLY": (0.85, 0.75, 0.95),
            "RELIEF": (0.50, 0.75, 0.50),
        }

        time_weight, safety_weight, payload_sensitivity = (
            defaults[self.mission_type]
        )

        return MissionProfile(
            mission_type=self.mission_type,
            priority=self.priority,
            origin=None,
            destination="hospital"
            if self.mission_type in ["TRAUMA", "MEDICAL_SUPPLY"]
            else "relief_centre",
            time_weight=time_weight,
            safety_weight=safety_weight,
            payload_sensitivity=payload_sensitivity,
            confidence=1.0,
            explanation="Fake mission for testing.",
        )


def create_service(mission_type, priority):
    service = MissionService()
    service.mission_agent = FakeMissionAgent(
        mission_type,
        priority,
    )
    return service


def test_trauma_returns_hospitals():
    service = create_service("TRAUMA", "CRITICAL")

    result = service.process_request(
        "Take a critically injured patient to a hospital immediately."
    )

    assert result.mission_type == "TRAUMA"
    assert result.facility_type == "hospital"
    assert len(result.candidate_facilities) == 6


def test_medical_supply_returns_hospitals():
    service = create_service("MEDICAL_SUPPLY", "HIGH")

    result = service.process_request(
        "Deliver blood to the hospital."
    )

    assert result.mission_type == "MEDICAL_SUPPLY"
    assert result.facility_type == "hospital"
    assert len(result.candidate_facilities) == 6


def test_relief_returns_relief_centres():
    service = create_service("RELIEF", "NORMAL")

    result = service.process_request(
        "Deliver food and drinking water to a relief centre."
    )

    assert result.mission_type == "RELIEF"
    assert result.facility_type == "relief_centre"
    assert len(result.candidate_facilities) == 5


def test_mission_state():
    service = create_service("TRAUMA", "CRITICAL")

    state = service.process_request(
        "Take a critically injured patient to a hospital."
    )

    assert state.mission_type == "TRAUMA"
    assert state.priority == "CRITICAL"
    assert state.facility_type == "hospital"
    assert len(state.candidate_facilities) == 6
    assert state.hazard_status is None
    assert state.selected_route is None