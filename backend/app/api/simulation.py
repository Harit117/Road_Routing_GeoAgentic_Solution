from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.api.schemas import (
    CreateSimulation,
    FrameLoading,
    FrameSummary,
    OnsetEntry,
    SimulationInfo,
)
from app.simulation.engine import STATUS_BANDS, Frame, Simulation
from app.simulation.flood_models import DEFAULT_MODEL, MODELS, create_model
from app.simulation.rainfall import PRESETS, RainfallSeries, from_preset, from_values

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


def _sim(request: Request) -> Simulation:
    sim = request.app.state.simulation
    if sim is None:
        raise HTTPException(409, "no simulation; POST /api/simulation first")
    return sim


def _summary(frame: Frame) -> FrameSummary:
    return FrameSummary(
        tick=frame.tick,
        time=frame.time,
        rainfall_mm_per_h=frame.rainfall_mm_per_h,
        cumulative_rain_mm=round(frame.cumulative_rain_mm, 2),
        status_counts=frame.status_counts,
    )


def _info(sim: Simulation) -> SimulationInfo:
    return SimulationInfo(
        model=sim.model.name,
        rainfall_source=sim.rainfall.source,
        rainfall_mm_per_h=sim.rainfall.mm_per_hour,
        step_minutes=sim.step_minutes,
        tick=sim.tick,
        total_ticks=len(sim.rainfall),
        finished=sim.finished,
        status_bands=dict(STATUS_BANDS),
        frames=[_summary(f) for f in sim.frames],
    )


def build_simulation(request_app, body: CreateSimulation) -> Simulation:
    start = body.start_time or datetime.now().replace(minute=0, second=0, microsecond=0)
    try:
        if body.scenario is not None:
            steps = request_app.state.risk_engine.scenario_steps(body.scenario)
            start = steps[0].time - timedelta(
                hours=steps[0].duration_hours
            )
            rainfall = RainfallSeries(
                [step.rainfall_mm / step.duration_hours for step in steps],
                start,
                f"historical_scenario:{body.scenario}",
            )
        elif body.preset is not None:
            rainfall = from_preset(body.preset, start)
        else:
            rainfall = from_values(body.rainfall_mm_per_h, start)
    except KeyError:
        raise HTTPException(
            422,
            "unknown rainfall preset or scenario; "
            f"presets={sorted(PRESETS)}, "
            "scenarios=['normal', 'moderate', 'heavy', 'extreme']",
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    model_name = body.model or DEFAULT_MODEL
    if model_name not in MODELS:
        raise HTTPException(422, f"unknown model; choose from {sorted(MODELS)}")
    return Simulation(
        request_app.state.network,
        create_model(model_name),
        rainfall,
        request_app.state.settings.step_minutes,
    )


@router.get("/models")
def models():
    return [{"name": m.name, "description": m.description} for m in MODELS.values()]


@router.get("/presets")
def presets():
    return PRESETS


@router.get("/scenarios")
def scenarios(request: Request):
    """Historical 48-hour rainfall scenarios (ERA5-derived), as mm/h per hour."""
    engine = request.app.state.risk_engine
    result = {}
    for name in engine.rainfall_provider.scenario_names:
        steps = engine.scenario_steps(name)
        result[name] = [round(s.rainfall_mm / s.duration_hours, 3) for s in steps]
    return result


@router.post("", response_model=SimulationInfo)
def create(body: CreateSimulation, request: Request):
    request.app.state.simulation = build_simulation(request.app, body)
    return _info(request.app.state.simulation)


@router.get("", response_model=SimulationInfo)
def info(request: Request):
    return _info(_sim(request))


@router.post("/step", response_model=SimulationInfo)
def step(request: Request, n: int = Query(1, ge=1)):
    sim = _sim(request)
    sim.run(max_steps=n)
    return _info(sim)


@router.post("/run", response_model=SimulationInfo)
def run(request: Request):
    sim = _sim(request)
    sim.run()
    return _info(sim)


class UpdateRainfall(BaseModel):
    rainfall_mm_per_h: list[float] = Field(min_length=1, max_length=720)


@router.post("/rainfall", response_model=SimulationInfo)
def update_rainfall(body: UpdateRainfall, request: Request):
    """Replace the rainfall series mid-storm (e.g. a heavier burst than
    forecast). Same model and start time; replays to the current tick."""
    sim = _sim(request)
    try:
        rainfall = from_values(body.rainfall_mm_per_h, sim.rainfall.start)
    except ValueError as e:
        raise HTTPException(422, str(e))
    replayed = Simulation(sim.network, create_model(sim.model.name), rainfall, sim.step_minutes)
    replayed.run(max_steps=sim.tick)
    request.app.state.simulation = replayed
    return _info(replayed)


@router.post("/reset", response_model=SimulationInfo)
def reset(request: Request):
    sim = _sim(request)
    sim.reset()
    return _info(sim)


@router.get("/frames/{tick}", response_model=FrameLoading)
def frame(tick: int, request: Request):
    sim = _sim(request)
    if not 0 <= tick < len(sim.frames):
        raise HTTPException(404, f"tick {tick} not simulated yet (have 0..{len(sim.frames) - 1})")
    f = sim.frames[tick]
    return FrameLoading(**_summary(f).model_dump(), loading=f.loading)


@router.get("/onset", response_model=list[OnsetEntry])
def onset(request: Request, limit: int = Query(100, ge=1, le=10000)):
    """Roads in the order they crossed the flood threshold: the relative
    flood-progression ranking routing will use."""
    sim = _sim(request)
    roads = sim.network.roads
    reached = sorted(
        (t, i) for i, t in enumerate(sim.onset_tick) if t is not None
    )[:limit]
    return [
        OnsetEntry(road_id=roads[i].road_id, index=i, name=roads[i].name, onset_tick=t)
        for t, i in reached
    ]
