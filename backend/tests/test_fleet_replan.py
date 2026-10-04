"""Live re-planning of a fleet that is already driving (fleet playback)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

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


@pytest.fixture(scope="module")
def fleet(client):
    plan = client.post(
        "/api/fleet/dispatch",
        json={"vehicles": [{"mission": "medical", "origin": p} for p in CLUSTER], "depart_tick": 4},
    ).json()
    return plan["plans"]["coordinated"]


def moving(fleet, step=1):
    """Each vehicle `step` segments into its route."""
    out = []
    for v in fleet:
        segs = v["route"]["segments"]
        k = min(step, len(segs) - 1)
        out.append(
            {
                "id": v["id"],
                "mission": "medical",
                "position": segs[k]["coords"][0],
                "road_id": segs[k]["road_id"],
                "follow_road_ids": [s["road_id"] for s in segs[k:]],
                "destination_id": v["destination"]["id"],
            }
        )
    return out


def replan(client, vehicles, minutes, **extra):
    r = client.post("/api/fleet/replan", json={"vehicles": vehicles, "depart_minutes": minutes, **extra})
    assert r.status_code == 200, r.text
    return {v["id"]: v for v in r.json()["vehicles"]}


def test_unchanged_conditions_keep_every_route(client, fleet):
    out = replan(client, moving(fleet), 240.5)
    assert all(v["reroute"]["changed"] is False for v in out.values())
    for v, m in zip(fleet, moving(fleet)):
        assert out[v["id"]]["route"]["road_ids"] == m["follow_road_ids"]


def test_rising_flood_reroutes_moving_vehicles(client, fleet):
    # Same positions, but the storm has moved on: roads ahead are now too wet.
    out = replan(client, moving(fleet), 330)
    rerouted = [v for v in out.values() if v["reroute"]["changed"]]
    assert rerouted
    assert any("over the ambulance" in v["reroute"]["reason"] for v in rerouted)


def test_incident_reroutes_only_affected_vehicles(client, fleet):
    target = fleet[2]
    blocked = target["route"]["segments"][4]["road_id"]
    out = replan(client, moving(fleet), 240.5, blocked_road_ids=[blocked])
    assert out[target["id"]]["reroute"]["changed"] is True
    assert "reported blocked" in out[target["id"]]["reroute"]["reason"]
    for v in out.values():
        # A vehicle already on the blocked road may drive off it; none enters it.
        assert blocked not in v["route"]["road_ids"][1:]
    users = {v["id"] for v in fleet if blocked in v["route"]["road_ids"][1:]}
    assert {vid for vid, v in out.items() if v["reroute"]["changed"]} <= users | {target["id"]}


def test_replan_validation(client, fleet):
    vehicles = moving(fleet)
    dup = [vehicles[0], vehicles[0]]
    assert client.post("/api/fleet/replan", json={"vehicles": dup, "depart_minutes": 240}).status_code == 422
    bad = [{**vehicles[0], "road_id": "nope"}]
    assert client.post("/api/fleet/replan", json={"vehicles": bad, "depart_minutes": 240}).status_code == 422
