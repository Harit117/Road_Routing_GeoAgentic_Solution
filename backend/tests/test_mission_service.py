from app.mission.mission_service import MissionService


def test_trauma_returns_hospitals():
    service = MissionService()

    result = service.process_request(
        "Take a critically injured patient to a hospital immediately."
    )

    assert result.mission_type == "TRAUMA"
    assert result.facility_type == "hospital"
    assert len(result.candidate_facilities) == 6


def test_medical_supply_returns_hospitals():
    service = MissionService()

    result = service.process_request(
        "Deliver blood to the hospital."
    )

    assert result.mission_type == "MEDICAL_SUPPLY"
    assert result.facility_type == "hospital"
    assert len(result.candidate_facilities) == 6


def test_relief_returns_relief_centres():
    service = MissionService()

    result = service.process_request(
        "Deliver food and drinking water to a relief centre."
    )

    assert result.mission_type == "RELIEF"
    assert result.facility_type == "relief_centre"
    assert len(result.candidate_facilities) == 5


def test_mission_state():
    service = MissionService()

    state = service.process_request(
        "Take a critically injured patient to a hospital."
    )

    assert state.mission_type == "TRAUMA"
    assert state.priority == "CRITICAL"
    assert state.facility_type == "hospital"
    assert len(state.candidate_facilities) == 6
    assert state.hazard_status is None
    assert state.selected_route is None