"""Routing-facing service adapter over the independent normalized risk engine."""

from datetime import datetime, timedelta

from fastapi import HTTPException

from app.api.schemas import (
    RoadFloodState,
    ScenarioSimulationRequest,
    ScenarioSimulationResponse,
)
from app.flood.config import RiskModelConfig
from app.flood.models import RainfallStep, RiskFrame, RoadRiskState
from app.flood.rainfall_provider import (
    PresetRainfallProvider,
    SCENARIO_NAMES,
    SequenceRainfallProvider,
)
from app.flood.risk_engine import RiskEngine
from app.simulation.engine import Simulation


MODEL_NAME = "normalized_susceptibility_bucket"
MODEL_STATUS = "scenario_based_prototype"


def model_status() -> dict:
    config = RiskModelConfig.from_environment()
    return {
        "implementation_status": MODEL_STATUS,
        "model_name": MODEL_NAME,
        "calibrated": False,
        "historical_susceptibility_integrated": True,
        "bucket_threshold_simulation_integrated": True,
        "live_rainfall_available": False,
        "current_state_source": "active simulation input (demo preset at startup)",
        "scenarios": list(SCENARIO_NAMES),
        "parameters": {
            "b_max": config.b_max,
            "base_fill_rate": config.base_fill_rate,
            "susceptibility_gain": config.susceptibility_gain,
            "rainfall_reference_mm": config.rainfall_reference_mm,
            "depth_weight": config.depth_weight,
            "hazard_weight": config.hazard_weight,
            "risk_bands": {
                "low_max": config.low_risk_max,
                "moderate_max": config.moderate_risk_max,
                "high_max": config.high_risk_max,
            },
        },
        "notes": (
            "Scores are relative prototype outputs under normalized historical "
            "rainfall forcing. They are not physically calibrated flood-depth or "
            "exact flood-onset predictions. No live rainfall feed is configured."
        ),
    }


def api_state(state: RoadRiskState) -> RoadFloodState:
    # Keep the existing routing contract's `loading` and `status` fields. The
    # loading field is now the road-relative risk score, so 1.0 means the
    # road-specific normalized threshold has been reached.
    if state.threshold_reached:
        status = "flooded"
    elif state.risk_score >= 0.8:
        status = "risky"
    elif state.risk_score >= 0.5:
        status = "watch"
    else:
        status = "safe"
    minutes = (
        round(state.time_to_threshold_hours * 60)
        if state.time_to_threshold_hours is not None
        else None
    )
    return RoadFloodState(
        road_id=state.road_id,
        status=status,
        loading=state.risk_score,
        susceptibility=state.susceptibility,
        threshold=state.threshold,
        current_flood_loading=state.current_flood_loading,
        risk_score=state.risk_score,
        risk_level=state.risk_level,
        threshold_reached=state.threshold_reached,
        elapsed_hours=state.elapsed_hours,
        time_to_threshold_hours=state.time_to_threshold_hours,
        rainfall_mm_per_h=state.rainfall_mm,
        cumulative_rain_mm=round(state.cumulative_rain_mm, 3),
        observed_at=state.observed_at,
        time_to_threshold_minutes=minutes,
        source=state.source,
    )


def _engine(app) -> RiskEngine:
    return app.state.risk_engine


def _active_series(sim: Simulation) -> list[RainfallStep]:
    duration = sim.dt_hours
    return [
        RainfallStep(
            time=sim.rainfall.start + timedelta(minutes=(tick + 1) * sim.step_minutes),
            rainfall_mm=sim.rainfall.mm_per_hour[tick] * duration,
            duration_hours=duration,
        )
        for tick in range(sim.tick)
    ]


def _active_frame(
    sim: Simulation, risk_engine: RiskEngine, road_ids: list[str] | None = None
) -> RiskFrame:
    steps = _active_series(sim)
    frames = risk_engine.iter_series(
        steps,
        source=sim.rainfall.source,
        road_ids=road_ids,
        start_time=sim.rainfall.start,
    )
    final = None
    for final in frames:
        pass
    if final is None:
        # iter_series still yields the zero-input initial state when the active
        # simulation has not advanced yet.
        raise RuntimeError("risk engine returned no initial state frame")
    return final


def states_for_simulation(
    sim: Simulation,
    risk_engine: RiskEngine,
    road_ids: list[str] | None = None,
) -> list[RoadFloodState]:
    return [api_state(state) for state in _active_frame(sim, risk_engine, road_ids).states]


def current_state(
    sim: Simulation,
    risk_engine: RiskEngine,
    road_id: str,
    scenario: str | None = None,
) -> RoadFloodState:
    if road_id not in sim.network.by_id:
        raise HTTPException(404, f"unknown road {road_id}")
    if scenario is None:
        return next(
            state
            for state in states_for_simulation(sim, risk_engine, [road_id])
            if state.road_id == road_id
        )
    try:
        frame = risk_engine.simulate_scenario(scenario, [road_id])
    except KeyError:
        raise HTTPException(422, f"unknown rainfall scenario; choose from {list(SCENARIO_NAMES)}")
    return api_state(frame.states[0])


def scenario_states(
    risk_engine: RiskEngine, scenario: str, road_ids: list[str] | None = None
) -> RiskFrame:
    try:
        return risk_engine.simulate_scenario(scenario, road_ids)
    except KeyError:
        raise HTTPException(422, f"unknown rainfall scenario; choose from {list(SCENARIO_NAMES)}")


def run_scenario(app, body: ScenarioSimulationRequest) -> ScenarioSimulationResponse:
    settings = app.state.settings
    engine = _engine(app)
    historical_name = body.scenario
    if historical_name is None and body.preset in SCENARIO_NAMES:
        historical_name = body.preset

    if historical_name is not None:
        steps = engine.scenario_steps(historical_name)
        source = f"historical_scenario:{historical_name}"
        scenario_name = body.scenario_name or historical_name
        step_minutes = 60
        start_time = steps[0].time - timedelta(hours=1)
    elif body.preset is not None:
        start_time = body.start_time or datetime.now().replace(
            minute=0, second=0, microsecond=0
        )
        try:
            steps = PresetRainfallProvider.get_series(
                body.preset, start_time, settings.step_minutes
            )
        except KeyError:
            raise HTTPException(422, "unknown rainfall preset")
        source = f"preset:{body.preset}"
        scenario_name = body.scenario_name
        step_minutes = settings.step_minutes
    else:
        start_time = body.start_time or datetime.now().replace(
            minute=0, second=0, microsecond=0
        )
        try:
            steps = SequenceRainfallProvider.from_values(
                body.rainfall_mm_per_h, start_time, settings.step_minutes
            )
        except ValueError as error:
            raise HTTPException(422, str(error))
        source = "manual"
        scenario_name = body.scenario_name
        step_minutes = settings.step_minutes

    final = None
    for final in engine.iter_series(
        steps,
        source=source,
        scenario=historical_name,
        start_time=start_time,
    ):
        pass
    if final is None:
        raise HTTPException(422, "scenario has no road states")
    return ScenarioSimulationResponse(
        scenario_name=scenario_name,
        model_status=MODEL_STATUS,
        model_name=MODEL_NAME,
        rainfall_source=source,
        step_minutes=step_minutes,
        started_at=start_time,
        completed_at=final.observed_at,
        states=[api_state(state) for state in final.states],
    )
