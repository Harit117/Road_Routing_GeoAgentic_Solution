from app.mission.routing_adapter import MissionRoutingAdapter


def test_trauma_maps_to_medical():
    adapter = MissionRoutingAdapter()

    mission = adapter.get_routing_mission("TRAUMA")

    assert mission.id == "medical"
    assert mission.facility_type == "hospital"


def test_medical_supply_maps_to_medical():
    adapter = MissionRoutingAdapter()

    mission = adapter.get_routing_mission("MEDICAL_SUPPLY")

    assert mission.id == "medical"
    assert mission.facility_type == "hospital"


def test_rescue_maps_to_evacuation():
    adapter = MissionRoutingAdapter()

    mission = adapter.get_routing_mission("RESCUE")

    assert mission.id == "evacuation"
    assert mission.facility_type == "relief_centre"


def test_relief_maps_to_evacuation():
    adapter = MissionRoutingAdapter()

    mission = adapter.get_routing_mission("RELIEF")

    assert mission.id == "evacuation"
    assert mission.facility_type == "relief_centre"