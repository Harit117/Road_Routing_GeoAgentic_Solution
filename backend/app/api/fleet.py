from dataclasses import asdict
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.routing.fleet import MAX_VEHICLES, FleetDispatcher, VehicleRequest
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
    sim = request.app.state.simulation
    if sim is None:
        raise HTTPException(409, "no active simulation; create one with POST /api/simulation")
    if body.depart_minutes is not None:
        depart = body.depart_minutes / sim.step_minutes
    else:
        depart = sim.tick if body.depart_tick is None else body.depart_tick
    if depart > len(sim.rainfall):
        raise HTTPException(422, f"departure must be within the {len(sim.rainfall)}-tick scenario")

    vehicles = []
    for k, v in enumerate(body.vehicles):
        mission = MISSIONS.get(v.mission)
        if mission is None:
            raise HTTPException(422, f"unknown mission {v.mission!r}; choose from {sorted(MISSIONS)}")
        vehicles.append(VehicleRequest(v.id or f"V{k + 1}", mission, v.origin, v.facility_id))
    if len({v.id for v in vehicles}) != len(vehicles):
        raise HTTPException(422, "vehicle ids must be unique")

    forecast = FloodForecast(forecast_frames(sim), sim.step_minutes, depart)
    try:
        result = _dispatcher(request).dispatch(vehicles, forecast, body.blocked_road_ids)
    except PlanningError as e:
        raise HTTPException(422, str(e))
    result["depart_tick"] = depart
    result["depart_time"] = sim.rainfall.start + timedelta(minutes=sim.step_minutes * depart)
    return result
