import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_network_loads(client):
    s = client.get("/api/network/summary").json()
    assert s["roads"] == 8616
    assert s["intersections"] == 3383
    assert s["flood_points"] > 0
    assert s["hazard_zones"] > 0

    roads = client.get("/api/network/roads").json()["features"]
    assert [f["properties"]["i"] for f in roads] == list(range(len(roads)))


def test_road_context_comes_from_link_tables(client):
    # Linked to flood point 40 (17.78 cm) in road_flood_point_links.csv.
    r = client.get("/api/network/roads/osm_299880378_313444440_0").json()
    assert r["flood_depth_cm"] == 17.78
    assert client.get("/api/network/roads/nope").status_code == 404


def test_simulation_lifecycle(client):
    info = client.post(
        "/api/simulation", json={"rainfall_mm_per_h": [0, 50, 50, 50, 50]}
    ).json()
    assert info["tick"] == 0 and info["total_ticks"] == 5
    assert info["frames"][0]["status_counts"]["safe"] == 8616

    info = client.post("/api/simulation/run").json()
    assert info["finished"]
    assert info["frames"][-1]["cumulative_rain_mm"] == 200
    # Loading never decreases while rain exceeds drainage.
    l2 = client.get("/api/simulation/frames/2").json()["loading"]
    l5 = client.get("/api/simulation/frames/5").json()["loading"]
    assert all(b >= a for a, b in zip(l2, l5))

    onset = client.get("/api/simulation/onset").json()
    assert onset and onset == sorted(onset, key=lambda e: e["onset_tick"])

    info = client.post("/api/simulation/reset").json()
    assert info["tick"] == 0 and len(info["frames"]) == 1
    assert client.get("/api/simulation/frames/3").status_code == 404


def test_higher_hazard_floods_first(client):
    client.post("/api/simulation", json={"preset": "intensifying_storm"})
    client.post("/api/simulation/run")
    onset = {e["road_id"]: e["onset_tick"] for e in client.get("/api/simulation/onset?limit=10000").json()}
    roads = client.get("/api/network/roads").json()["features"]
    very_high = [onset[f["properties"]["id"]] for f in roads if f["properties"]["hazard"] == "Very High" and f["properties"]["id"] in onset]
    low = [onset.get(f["properties"]["id"], 99) for f in roads if f["properties"]["hazard"] == "Low"]
    assert very_high and min(very_high) < min(low)


def test_bad_input_rejected(client):
    assert client.post("/api/simulation", json={}).status_code == 422
    assert client.post("/api/simulation", json={"preset": "nope"}).status_code == 422
    assert client.post("/api/simulation", json={"rainfall_mm_per_h": [-1]}).status_code == 422
    assert client.post("/api/simulation", json={"preset": "cloudburst", "model": "nope"}).status_code == 422


def test_routing_is_stubbed(client):
    assert len(client.get("/api/missions").json()) == 3
    r = client.post("/api/route", json={"mission": "medical", "origin": [80.22, 12.98]})
    assert r.status_code == 501
