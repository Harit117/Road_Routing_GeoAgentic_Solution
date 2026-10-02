import json
from collections import Counter
from functools import cache

from fastapi import APIRouter, HTTPException, Request, Response

from app.network.models import RoadNetwork

router = APIRouter(prefix="/api/network", tags=["network"])


def _network(request: Request) -> RoadNetwork:
    return request.app.state.network


# The network never changes while the server runs, so its large GeoJSON
# payloads are serialised once.
@cache
def _roads_geojson(network: RoadNetwork) -> bytes:
    features = [
        {
            "type": "Feature",
            "properties": {
                "i": r.index,
                "id": r.road_id,
                "name": r.name,
                "highway": r.highway,
                "oneway": r.oneway,
                "hazard": r.hazard_category,
                "depth_cm": r.flood_depth_cm,
                "length_m": round(r.length_m, 1),
            },
            "geometry": {"type": "LineString", "coordinates": r.coords},
        }
        for r in network.roads
    ]
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


@cache
def _hazard_geojson(network: RoadNetwork) -> bytes:
    return json.dumps(
        {"type": "FeatureCollection", "features": network.hazard_zones}
    ).encode()


@router.get("/summary")
def summary(request: Request):
    net = _network(request)
    return {
        "region": net.region,
        "bbox": net.bbox,
        "roads": len(net.roads),
        "intersections": len(net.nodes),
        "total_length_km": round(sum(r.length_m for r in net.roads) / 1000, 1),
        "roads_by_hazard": Counter(r.hazard_category or "None" for r in net.roads),
        "roads_near_flood_points": sum(1 for r in net.roads if r.flood_point_count),
        "flood_points": len(net.flood_points),
        "hazard_zones": len(net.hazard_zones),
    }


@router.get("/roads")
def roads(request: Request):
    return Response(_roads_geojson(_network(request)), media_type="application/json")


@router.get("/roads/{road_id}")
def road(road_id: str, request: Request):
    net = _network(request)
    r = net.by_id.get(road_id)
    if r is None:
        raise HTTPException(404, f"unknown road {road_id}")
    data = {k: getattr(r, k) for k in r.__slots__ if k != "coords"}
    sim = request.app.state.simulation
    if sim is not None:
        data["loading_history"] = [f.loading[r.index] for f in sim.frames]
        data["onset_tick"] = sim.onset_tick[r.index]
    return data


@router.get("/hazard-zones")
def hazard_zones(request: Request):
    return Response(_hazard_geojson(_network(request)), media_type="application/json")


@router.get("/flood-points")
def flood_points(request: Request):
    return _network(request).flood_points
