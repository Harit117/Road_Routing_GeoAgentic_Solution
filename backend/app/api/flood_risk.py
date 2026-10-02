from fastapi import APIRouter, HTTPException, Request

from app.api.schemas import (
    RoadFloodState,
    RoadFloodStateBatchRequest,
    RoadFloodStateBatchResponse,
    ScenarioSimulationRequest,
    ScenarioSimulationResponse,
)
from app.flood.rainfall_provider import SCENARIO_NAMES
from app.simulation.engine import Simulation
from app.simulation.flood_risk_service import (
    current_state,
    api_state,
    model_status,
    run_scenario,
    scenario_states,
    states_for_simulation,
)

router = APIRouter(prefix="/api/flood-risk", tags=["flood risk"])


def _simulation(request: Request) -> Simulation:
    sim = request.app.state.simulation
    if sim is None:
        raise HTTPException(409, "no active simulation; create one with POST /api/simulation")
    return sim


@router.get("/model-status")
def get_model_status():
    """Describe prototype calibration, rainfall-source, and model status."""
    return model_status()


@router.get("/roads/{road_id}", response_model=RoadFloodState)
def get_road_state(
    road_id: str,
    request: Request,
    scenario: str | None = None,
):
    """Return active-input state, or the final state under an optional scenario."""
    if scenario is not None and scenario not in SCENARIO_NAMES:
        raise HTTPException(422, f"unknown scenario; choose from {list(SCENARIO_NAMES)}")
    return current_state(
        _simulation(request), request.app.state.risk_engine, road_id, scenario
    )


@router.post("/roads:batch", response_model=RoadFloodStateBatchResponse)
def get_road_states(body: RoadFloodStateBatchRequest, request: Request):
    """Return active-input or selected scenario states for requested roads."""
    sim = _simulation(request)
    by_id = sim.network.by_id
    requested = list(dict.fromkeys(body.road_ids))
    known = [road_id for road_id in requested if road_id in by_id]
    unknown = [road_id for road_id in requested if road_id not in by_id]
    if body.scenario is None:
        if known:
            states = states_for_simulation(
                sim, request.app.state.risk_engine, known
            )
            observed_at = states[0].observed_at
        else:
            states = []
            observed_at = sim.frames[-1].time
    else:
        if known:
            frame = scenario_states(
                request.app.state.risk_engine, body.scenario, known
            )
            states = [api_state(state) for state in frame.states]
            observed_at = frame.observed_at
        else:
            states = []
            observed_at = sim.frames[-1].time
    return RoadFloodStateBatchResponse(
        states=states,
        unknown_road_ids=unknown,
        observed_at=observed_at,
        scenario=body.scenario,
    )


@router.post("/simulate", response_model=ScenarioSimulationResponse)
def simulate_scenario(body: ScenarioSimulationRequest, request: Request):
    """Run an isolated rainfall scenario and return each road's final state and threshold time."""
    return run_scenario(request.app, body)
