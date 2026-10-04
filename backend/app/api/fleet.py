from dataclasses import asdict
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.routing.fleet import MAX_VEHICLES, FleetDispatcher, MovingVehicle, VehicleRequest
from app.routing.forecast import FloodForecast, forecast_frames
from app.routing.missions import MISSIONS
from app.routing.planner import PlanningError

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


class FleetVehicle(BaseModel):
    id: str | None = Field(None, max_length=20, description="Defaults to V1, V2, ...")
    mission: str
    origin: tuple[float, float] = Field(description="(lon, lat); snapped to the nearest road")
    facility_id: str | None = None


class DispatchRequest(BaseModel):
    vehicles: list[FleetVehicle] = Field(min_length=1, max_length=MAX_VEHICLES)
    depart_tick: int | None = Field(None, ge=0)
    depart_minutes: float | None = Field(None, ge=0)
    blocked_road_ids: list[str] | None = Field(None, max_length=500)


class MovingFleetVehicle(BaseModel):
    id: str = Field(max_length=20)
    mission: str
    position: tuple[float, float] = Field(description="Current (lon, lat)")
    road_id: str = Field(description="Road the vehicle is on")
    follow_road_ids: list[str] = Field(min_length=1, max_length=5000, description="Rest of its route, from road_id")
    destination_id: str
    forced: bool = False


class ReplanRequest(BaseModel):
    vehicles: list[MovingFleetVehicle] = Field(min_length=1, max_length=MAX_VEHICLES)
    depart_minutes: float = Field(ge=0, description="Current trip clock, minutes since scenario start")
    blocked_road_ids: list[str] | None = Field(None, max_length=500)


def _forecast(request: Request, depart_minutes: float | None, depart_tick: int | None) -> FloodForecast:
    sim = request.app.state.simulation
    if sim is None:
        raise HTTPException(409, "no active simulation; create one with POST /api/simulation")
    if depart_minutes is not None:
        depart = depart_minutes / sim.step_minutes
    else:
        depart = sim.tick if depart_tick is None else depart_tick
    if depart > len(sim.rainfall):
        raise HTTPException(422, f"departure must be within the {len(sim.rainfall)}-tick scenario")
    return FloodForecast(forecast_frames(sim), sim.step_minutes, depart)


def _mission(name: str):
    mission = MISSIONS.get(name)
    if mission is None:
        raise HTTPException(422, f"unknown mission {name!r}; choose from {sorted(MISSIONS)}")
    return mission


def _dispatcher(request: Request) -> FleetDispatcher:
    if getattr(request.app.state, "fleet", None) is None:
        request.app.state.fleet = FleetDispatcher(request.app.state.planner)
    return request.app.state.fleet


@router.get("/rules")
def rules(request: Request):
    return asdict(_dispatcher(request).rules)


@router.post("/dispatch")
def dispatch(body: DispatchRequest, request: Request):
    """Route several vehicles at once, splitting them in flood zones so they
    do not jam; also returns the uncoordinated plan for comparison."""
    forecast = _forecast(request, body.depart_minutes, body.depart_tick)
    vehicles = [
        VehicleRequest(v.id or f"V{k + 1}", _mission(v.mission), v.origin, v.facility_id)
        for k, v in enumerate(body.vehicles)
    ]
    if len({v.id for v in vehicles}) != len(vehicles):
        raise HTTPException(422, "vehicle ids must be unique")
    try:
        result = _dispatcher(request).dispatch(vehicles, forecast, body.blocked_road_ids)
    except PlanningError as e:
        raise HTTPException(422, str(e))
    sim = request.app.state.simulation
    result["depart_tick"] = forecast.depart_tick
    result["depart_time"] = sim.rainfall.start + timedelta(minutes=sim.step_minutes * forecast.depart_tick)
    return result


@router.post("/replan")
def replan(body: ReplanRequest, request: Request):
    """Live re-check of a fleet that is driving: re-route vehicles whose road
    ahead will flood or is blocked, keeping the congestion rules."""
    forecast = _forecast(request, body.depart_minutes, None)
    vehicles = [
        MovingVehicle(
            v.id, _mission(v.mission), v.position, v.road_id, v.follow_road_ids, v.destination_id, v.forced
        )
        for v in body.vehicles
    ]
    if len({v.id for v in vehicles}) != len(vehicles):
        raise HTTPException(422, "vehicle ids must be unique")
    try:
        return _dispatcher(request).replan(vehicles, forecast, body.blocked_road_ids)
    except PlanningError as e:
        raise HTTPException(422, str(e))
