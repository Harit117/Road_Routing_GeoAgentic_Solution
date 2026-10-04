from app.mission.facility_resolver import FacilityResolver


def test_find_hospitals():

    resolver = FacilityResolver()

    hospitals = resolver.find_by_type("hospital")

    assert len(hospitals) == 6


def test_find_relief_centres():

    resolver = FacilityResolver()

    centres = resolver.find_by_type("relief_centre")

    assert len(centres) == 5


def test_find_facility_by_id():

    resolver = FacilityResolver()

    facility = resolver.find_by_id("H3")

    assert facility is not None
    assert facility["id"] == "H3"
    assert facility["type"] == "hospital"
    assert facility["node_id"] == 251172944