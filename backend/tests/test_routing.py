import networkx as nx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routing.astar import Start, astar
from app.routing.planner import fastest_edge

ORIGIN = [80.2120, 12.9790]  # 2nd Main Road, central Velachery
SOUTH_EAST = [80.2250, 12.9680]  # floods early under the demo storm


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        c.post("/api/simulation", json={"preset": "intensifying_storm"})
        yield c


def route(client, **body):
    return client.post("/api/route", json={"mission": "medical", "origin": ORIGIN, **body})


def test_missions_and_facilities(client):
    missions = {m["id"]: m for m in client.get("/api/missions").json()}
    assert set(missions) == {"medical", "evacuation"}
    assert missions["medical"]["facility_type"] == "hospital"
    assert missions["evacuation"]["facility_type"] == "relief_centre"

    facilities = client.get("/api/facilities").json()
    assert {f["type"] for f in facilities} == {"hospital", "relief_centre"}
    assert all(f["road_indices"] for f in facilities)
    assert len(client.get("/api/facilities?type=hospital").json()) == 6


def test_astar_matches_dijkstra_on_travel_time():
    with TestClient(app):
        graph = app.state.planner.graph
        net = graph.network
        g = nx.DiGraph()
        for r in net.roads:
            w = graph.travel_min[r.index]
            if not g.has_edge(r.u, r.v) or g[r.u][r.v]["w"] > w:
                g.add_edge(r.u, r.v, w=w)
        nodes = list(net.nodes)
        for a, b in [(nodes[0], nodes[500]), (nodes[100], nodes[2500]), (nodes[1200], nodes[3000])]:
            found = astar(graph, [Start(a, 0.0, 0.0)], b, fastest_edge(graph))
            if found is None:
                assert not nx.has_path(g, a, b)
                continue
            expected = nx.dijkstra_path_length(g, a, b, weight="w")
            assert found.cost == pytest.approx(expected)


def test_dry_network_takes_fastest_route(client):
    body = route(client, depart_tick=0).json()
    assert body["status"] == "ok"
    assert body["destination"]["type"] == "hospital"
    assert body["route"]["max_loading"] == 0
    assert body["fastest"]["same_as_route"] is True
    assert body["origin"]["road_name"] == "2nd Main Road"
    # Options: reachable ones first, cheapest first.
    costs = [o["cost"] for o in body["options"] if o["state"] == "ok"]
    assert costs == sorted(costs)


def test_flood_aware_route_detours_and_respects_limit(client):
    body = route(client, depart_tick=5, facility_id="H3").json()
    assert body["status"] == "ok"
    r, f = body["route"], body["fastest"]
    assert r["blocked_m"] == 0
    assert all(s["loading"] < 0.8 for s in r["segments"] if not s["is_start"])
    assert f["same_as_route"] is False and f["blocked_m"] > 0
    assert r["minutes"] > f["minutes"]  # the detour costs time


def test_floods_change_the_chosen_hospital(client):
    early = route(client, depart_tick=0).json()["destination"]["id"]
    states = {o["facility"]["id"]: o["state"] for o in route(client, depart_tick=6).json()["options"]}
    assert "cut_off" in states.values() or "site_flooded" in states.values()
    assert early in states


def test_no_safe_route_falls_back_to_least_flooded(client):
    body = client.post(
        "/api/route", json={"mission": "medical", "origin": SOUTH_EAST, "depart_tick": 6}
    ).json()
    assert body["status"] == "no_safe_route"
    assert body["route"] is not None and body["route"]["blocked_m"] > 0
    assert any("least-flooded" in w for w in body["warnings"])


def test_evacuation_goes_to_relief_centres(client):
    body = client.post(
        "/api/route", json={"mission": "evacuation", "origin": ORIGIN, "depart_tick": 0}
    ).json()
    assert body["destination"]["type"] == "relief_centre"
    assert all(o["facility"]["type"] == "relief_centre" for o in body["options"])


def test_routing_does_not_advance_the_map_simulation(client):
    before = client.get("/api/simulation").json()["tick"]
    route(client, depart_tick=9)
    assert client.get("/api/simulation").json()["tick"] == before


def test_bad_route_requests(client):
    assert route(client, depart_tick=99).status_code == 422
    assert route(client, facility_id="nope").status_code == 422
    assert client.post("/api/route", json={"mission": "rescue", "origin": ORIGIN}).status_code == 422
    far = client.post("/api/route", json={"mission": "medical", "origin": [80.30, 13.10]})
    assert far.status_code == 422 and "not near a road" in far.json()["detail"]


# ---------- drive mode: mid-trip replanning ----------

DRIVE_ORIGIN = [80.2081, 12.9858]


def _trip(client, minutes=300):
    client.post("/api/simulation", json={"preset": "intensifying_storm"})
    plan = client.post(
        "/api/route",
        json={"mission": "medical", "origin": DRIVE_ORIGIN, "depart_minutes": minutes, "facility_id": "H3"},
    ).json()
    segs = plan["route"]["segments"]
    here = segs[3]  # vehicle partway along the route
    return plan, segs, here, [s["road_id"] for s in segs[3:]], minutes + here["enter_min"]


def _replan(client, here, follow, now, **extra):
    return client.post(
        "/api/route",
        json={
            "mission": "medical",
            "origin": here["coords"][0],
            "origin_road_id": follow[0],
            "follow_road_ids": follow,
            "depart_minutes": now,
            "facility_id": "H3",
            **extra,
        },
    ).json()


def test_following_unchanged_forecast_keeps_route(client):
    plan, _, here, follow, now = _trip(client)
    body = _replan(client, here, follow, now)
    assert body["reroute"] == {"changed": False, "reason": None}
    assert body["route"]["road_ids"] == follow
    assert body["depart_minutes"] == pytest.approx(now, abs=1e-3)


def test_blocked_road_ahead_forces_reroute(client):
    _, segs, here, follow, now = _trip(client)
    ahead = segs[10]
    body = _replan(client, here, follow, now, blocked_road_ids=[ahead["road_id"]])
    assert body["reroute"]["changed"] is True
    assert "reported blocked" in body["reroute"]["reason"]
    assert ahead["road_id"] not in body["route"]["road_ids"]
    assert ahead["road_id"] not in body["fastest"]["road_ids"]  # incidents bind every route


def test_rainfall_update_replays_to_current_tick(client):
    client.post("/api/simulation", json={"preset": "intensifying_storm"})
    client.post("/api/simulation/step?n=4")
    rain = client.get("/api/simulation").json()["rainfall_mm_per_h"]
    before = client.get("/api/simulation/frames/4").json()["loading"]
    rain[4] += 80
    info = client.post("/api/simulation/rainfall", json={"rainfall_mm_per_h": rain}).json()
    assert info["tick"] == 4 and info["rainfall_mm_per_h"][4] == rain[4]
    # Rain in hour 4 only affects frames after tick 4.
    assert client.get("/api/simulation/frames/4").json()["loading"] == before
    assert client.post("/api/simulation/rainfall", json={"rainfall_mm_per_h": [-5]}).status_code == 422


def test_snap_finds_clicked_road(client):
    body = client.get("/api/snap", params={"lon": ORIGIN[0], "lat": ORIGIN[1]}).json()
    assert body["name"] == "2nd Main Road" and body["coords"]
    assert client.get("/api/snap", params={"lon": 80.30, "lat": 13.10}).status_code == 404
