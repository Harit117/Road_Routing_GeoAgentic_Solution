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


def test_flood_risk_contract_for_routing(client):
    road_id = "osm_299880378_313444440_0"
    assert client.get("/api/health").json()["status"] == "ok"

    status = client.get("/api/flood-risk/model-status").json()
    assert status["implementation_status"] == "scenario_based_prototype"
    assert status["calibrated"] is False
    assert status["historical_susceptibility_integrated"] is True
    assert status["live_rainfall_available"] is False

    single = client.get(f"/api/flood-risk/roads/{road_id}")
    assert single.status_code == 200
    state = single.json()
    assert state["road_id"] == road_id
    assert state["status"] in {"safe", "watch", "risky", "flooded"}
    assert 0 <= state["loading"] <= 1
    assert state["risk_score"] == state["loading"]
    assert 0 <= state["susceptibility"] <= 1
    assert state["threshold"] >= 0
    assert state["risk_level"] in {"LOW", "MODERATE", "HIGH", "VERY_HIGH", "CRITICAL"}
    assert state["source"].startswith("preset:")
    assert "time_to_threshold_hours" in state
    assert client.get("/api/flood-risk/roads/not-a-road").status_code == 404

    batch = client.post(
        "/api/flood-risk/roads:batch",
        json={"road_ids": [road_id, "not-a-road", road_id]},
    )
    assert batch.status_code == 200
    batch_body = batch.json()
    assert [item["road_id"] for item in batch_body["states"]] == [road_id]
    assert batch_body["unknown_road_ids"] == ["not-a-road"]
    assert batch_body["model_status"] == "scenario_based_prototype"

    scenario_batch = client.post(
        "/api/flood-risk/roads:batch",
        json={"road_ids": [road_id], "scenario": "normal"},
    )
    assert scenario_batch.status_code == 200
    assert scenario_batch.json()["scenario"] == "normal"
    assert scenario_batch.json()["states"][0]["source"] == "historical_scenario:normal"


def test_scenario_simulation_is_isolated_and_returns_model_state(client):
    before = client.get("/api/simulation").json()["tick"]
    response = client.post(
        "/api/flood-risk/simulate",
        json={
            "scenario_name": "routing integration smoke scenario",
            "rainfall_mm_per_h": [0, 50, 80],
            "start_time": "2026-10-03T12:00:00Z",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scenario_name"] == "routing integration smoke scenario"
    assert body["model_status"] == "scenario_based_prototype"
    assert body["model_name"] == "normalized_susceptibility_bucket"
    assert body["started_at"].startswith("2026-10-03T12:00:00")
    assert body["states"]
    assert all("time_to_threshold_minutes" in item for item in body["states"])
    assert all("time_to_threshold_hours" in item for item in body["states"])
    assert client.get("/api/simulation").json()["tick"] == before


def test_historical_scenario_request_and_health_alias(client):
    road_id = "osm_299880378_313444440_0"
    response = client.post(
        "/api/flood-risk/simulate",
        json={"scenario": "heavy"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scenario_name"] == "heavy"
    assert body["rainfall_source"] == "historical_scenario:heavy"
    assert len(body["states"]) == 8616
    assert road_id in {state["road_id"] for state in body["states"]}
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/health").json()["status"] == "ok"
