from fastapi import APIRouter, HTTPException, Request

from app.api.schemas import (
    RoadFloodState,
    RoadFloodStateBatchRequest,
    RoadFloodStateBatchResponse,
    ScenarioSimulationRequest,
    ScenarioSimulationResponse,
)
from app.simulation.engine import Simulation
from app.simulation.flood_risk_service import (
    current_state,
    model_status,
    run_scenario,
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
    """Describe whether returned risk values come from a real or placeholder model."""
    return model_status()


@router.get("/roads/{road_id}", response_model=RoadFloodState)
def get_road_state(road_id: str, request: Request):
    """Return one road's state at the latest tick of the active simulation."""
    return current_state(_simulation(request), road_id)


@router.post("/roads:batch", response_model=RoadFloodStateBatchResponse)
def get_road_states(body: RoadFloodStateBatchRequest, request: Request):
    """Return routing inputs for requested road IDs; unknown IDs are reported separately."""
    sim = _simulation(request)
    all_states = states_for_simulation(sim)
    by_id = {state.road_id: state for state in all_states}
    states = [by_id[road_id] for road_id in dict.fromkeys(body.road_ids) if road_id in by_id]
    unknown = list(dict.fromkeys(road_id for road_id in body.road_ids if road_id not in by_id))
    observed_at = sim.frames[-1].time
    return RoadFloodStateBatchResponse(
        states=states,
        unknown_road_ids=unknown,
        observed_at=observed_at,
    )


@router.post("/simulate", response_model=ScenarioSimulationResponse)
def simulate_scenario(body: ScenarioSimulationRequest, request: Request):
    """Run an isolated rainfall scenario and return each road's final state and threshold time."""
    return run_scenario(request.app, body)
