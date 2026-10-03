from dataclasses import asdict
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.routing.forecast import FloodForecast, forecast_frames
from app.routing.missions import MISSIONS
from app.routing.planner import Planner, PlanningError

router = APIRouter(prefix="/api", tags=["routing"])


class RouteRequest(BaseModel):
    mission: str = Field(description="Mission profile id, e.g. 'medical' or 'evacuation'")
    origin: tuple[float, float] = Field(description="Start point as (lon, lat); snapped to the nearest road")
    facility_id: str | None = Field(None, description="Force a destination; default picks the best reachable one")
    depart_tick: int | None = Field(
        None, ge=0, description="Simulation tick to depart at; default is the active simulation's current tick"
    )
    depart_minutes: float | None = Field(
        None, ge=0, description="Departure as minutes since the scenario start; overrides depart_tick (used mid-trip)"
    )
    origin_road_id: str | None = Field(
        None, description="Road the vehicle is on; pins snapping to it instead of the nearest road"
    )
    follow_road_ids: list[str] | None = Field(
        None,
        max_length=5000,
        description="Route being driven, starting with origin_road_id; kept unless it became unsafe or clearly worse",
    )
    blocked_road_ids: list[str] | None = Field(
        None, max_length=500, description="Roads reported blocked (incidents); closed in both directions"
    )


@router.get("/missions")
def missions():
    return [asdict(m) for m in MISSIONS.values()]


@router.get("/facilities")
def facilities(request: Request, type: str | None = None):
    return [
        {**asdict(f), "road_indices": list(f.road_indices)}
        for f in request.app.state.planner.facilities.values()
        if type is None or f.type == type
    ]


@router.get("/snap")
def snap(lon: float, lat: float, request: Request):
    """Nearest road to a point (used to report an incident on a clicked road)."""
    graph = request.app.state.planner.graph
    s = graph.snap(lon, lat)
    if s is None:
        raise HTTPException(404, "no road near this point")
    road = graph.network.roads[s.road_index]
    return {
        "road_id": road.road_id,
        "name": road.name,
        "point": list(s.point),
        "distance_m": round(s.distance_m, 1),
        "coords": [list(c) for c in road.coords],
    }


@router.post("/route")
def route(body: RouteRequest, request: Request):
    """Flood-aware route from a clicked start point to the best reachable
    facility for the mission, using the loading each road is forecast to
    have when the vehicle reaches it."""
    mission = MISSIONS.get(body.mission)
    if mission is None:
        raise HTTPException(422, f"unknown mission; choose from {sorted(MISSIONS)}")
    sim = request.app.state.simulation
    if sim is None:
        raise HTTPException(409, "no active simulation; create one with POST /api/simulation")
    if body.depart_minutes is not None:
        depart = body.depart_minutes / sim.step_minutes  # fractional tick
    else:
        depart = sim.tick if body.depart_tick is None else body.depart_tick
    if depart > len(sim.rainfall):
        raise HTTPException(422, f"departure must be within the {len(sim.rainfall)}-tick scenario")

    forecast = FloodForecast(forecast_frames(sim), sim.step_minutes, depart)
    planner: Planner = request.app.state.planner
    try:
        result = planner.plan(
            mission,
            body.origin,
            forecast,
            body.facility_id,
            origin_road_id=body.origin_road_id,
            follow_road_ids=body.follow_road_ids,
            blocked_road_ids=body.blocked_road_ids,
        )
    except PlanningError as e:
        raise HTTPException(422, str(e))
    result["depart_time"] = sim.rainfall.start + timedelta(minutes=sim.step_minutes * depart)
    return result
