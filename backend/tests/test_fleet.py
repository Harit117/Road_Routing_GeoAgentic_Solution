import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routing.fleet import CongestionRules

# Five ambulances placed close together in central Velachery.
CLUSTER = [
    [80.2120, 12.9790],
    [80.2112, 12.9783],
    [80.2128, 12.9798],
    [80.2105, 12.9795],
    [80.2135, 12.9785],
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        c.post("/api/simulation", json={"preset": "intensifying_storm"})
        yield c


def dispatch(client, tick, points=CLUSTER, mission="medical"):
    r = client.post(
        "/api/fleet/dispatch",
        json={"vehicles": [{"mission": mission, "origin": p} for p in points], "depart_tick": tick},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_zone_rules():
    rules = CongestionRules()
    assert rules.zone(hazard_rank=0, loading=0.1) is None  # green: sharing is fine
    assert rules.zone(hazard_rank=4, loading=0.0) == "orange"  # High hazard zone
    assert rules.zone(hazard_rank=0, loading=0.6) == "orange"  # wet road
    assert rules.zone(hazard_rank=5, loading=0.0) == "red"  # Very High hazard zone
    assert rules.zone(hazard_rank=2, loading=0.9) == "red"  # very wet road
    assert rules.cap("red") < rules.cap("orange")


def test_dry_network_needs_no_splitting(client):
    body = dispatch(client, tick=0)
    assert body["report"]["coordinated"]["overloaded_roads"] == 0
    assert body["report"]["independent"]["overloaded_roads"] == 0
    assert not any(v["changed"] for v in body["plans"]["coordinated"])
    assert [v["id"] for v in body["plans"]["coordinated"]] == ["V1", "V2", "V3", "V4", "V5"]


def test_flood_zones_split_the_fleet(client):
    body = dispatch(client, tick=5)
    coordinated = body["report"]["coordinated"]
    independent = body["report"]["independent"]
    assert independent["overloaded_roads"] > 0
    assert coordinated["overloaded_roads"] < independent["overloaded_roads"]
    assert coordinated["estimated_jam_delay_min"] < independent["estimated_jam_delay_min"]
    split = [v for v in body["plans"]["coordinated"] if v["changed"]]
    assert split and all(v["extra_minutes"] >= 0 for v in split)
    # Every overloaded road really is over its zone cap.
    for road in coordinated["roads"] + independent["roads"]:
        assert len(road["vehicles"]) > road["cap"]


def test_first_vehicle_keeps_its_best_route(client):
    # Routed first, so nobody is in its way: same as the uncoordinated plan.
    body = dispatch(client, tick=5)
    first = body["routing_order"][0]
    v = next(v for v in body["plans"]["coordinated"] if v["id"] == first)
    assert v["changed"] is False


def test_medical_vehicles_are_routed_first(client):
    r = client.post(
        "/api/fleet/dispatch",
        json={
            "vehicles": [
                {"id": "BUS", "mission": "evacuation", "origin": CLUSTER[0]},
                {"id": "AMB", "mission": "medical", "origin": CLUSTER[1]},
            ],
            "depart_tick": 5,
        },
    ).json()
    assert r["routing_order"] == ["AMB", "BUS"]
    dest = {v["id"]: v["destination"]["type"] for v in r["plans"]["coordinated"]}
    assert dest == {"AMB": "hospital", "BUS": "relief_centre"}


def test_fleet_request_validation(client):
    assert client.post("/api/fleet/dispatch", json={"vehicles": []}).status_code == 422
    bad = client.post("/api/fleet/dispatch", json={"vehicles": [{"mission": "rescue", "origin": CLUSTER[0]}]})
    assert bad.status_code == 422
    dup = client.post(
        "/api/fleet/dispatch",
        json={"vehicles": [{"id": "A", "mission": "medical", "origin": p} for p in CLUSTER[:2]]},
    )
    assert dup.status_code == 422
    far = client.post("/api/fleet/dispatch", json={"vehicles": [{"mission": "medical", "origin": [80.30, 13.10]}]})
    assert far.status_code == 422 and far.json()["detail"].startswith("V1:")
    assert client.get("/api/fleet/rules").json()["red_cap"] == 1


EIGHT = CLUSTER + [[80.2118, 12.9802], [80.2100, 12.9780], [80.2140, 12.9795]]


def test_congestion_changes_route_not_hospital(client):
    body = dispatch(client, tick=5, points=EIGHT)
    own = {v["id"]: v["destination"]["id"] for v in body["plans"]["independent"]}
    for v in body["plans"]["coordinated"]:
        d = v["destination_decision"]
        assert d["home"] == own[v["id"]]
        if v["destination"]["id"] != own[v["id"]]:
            # Only allowed with a real, recorded saving above both margins.
            assert d["switched"] and d["saving_min"] >= d["needed_min"]
    # The fleet still gets the jam benefit from re-routing alone.
    assert body["report"]["coordinated"]["estimated_jam_delay_min"] < body["report"]["independent"]["estimated_jam_delay_min"]


def test_hospital_switch_needs_clear_saving(client):
    rules = CongestionRules()
    for tick in (5, 6):
        for v in dispatch(client, tick=tick, points=EIGHT)["plans"]["coordinated"]:
            d = v["destination_decision"]
            if d and d["switched"] and "saving_min" in d:
                needed = max(rules.switch_min_minutes, rules.switch_min_fraction * (d["home_minutes"] + d["home_jam_delay_min"]))
                assert d["saving_min"] >= needed - 1e-6
                assert v["destination"]["id"] == d["chosen"] != d["home"]


def test_forced_facility_is_never_switched(client):
    r = client.post(
        "/api/fleet/dispatch",
        json={"vehicles": [{"mission": "medical", "origin": p, "facility_id": "H3"} for p in CLUSTER], "depart_tick": 5},
    ).json()
    assert {v["destination"]["id"] for v in r["plans"]["coordinated"]} == {"H3"}
