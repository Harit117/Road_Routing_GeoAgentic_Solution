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
